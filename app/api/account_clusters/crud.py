import random
import string
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.account_clusters import models, schemas
from app.api.citizens.models import Citizen
from app.api.email_logs.crud import email_log
from app.api.email_logs.schemas import EmailEvent
from app.core.logger import logger


def generate_verification_code() -> str:
    """Generate a 6-digit verification code."""
    return ''.join(random.choices(string.digits, k=6))


def get_cluster_id_for_citizen(db: Session, citizen_id: int) -> Optional[int]:
    """Find the cluster ID for a given citizen."""
    member = (
        db.query(models.AccountClusterMember)
        .filter(models.AccountClusterMember.citizen_id == citizen_id)
        .first()
    )
    return member.cluster_id if member else None


def get_linked_citizen_ids(db: Session, citizen_id: int) -> List[int]:
    """
    Get all citizen IDs in the same cluster (transitive linking supported).
    Returns list including the original citizen_id.
    """
    cluster_id = get_cluster_id_for_citizen(db, citizen_id)

    if not cluster_id:
        return [citizen_id]  # Not in any cluster, return self only

    # Get all members in the cluster
    members = (
        db.query(models.AccountClusterMember)
        .filter(models.AccountClusterMember.cluster_id == cluster_id)
        .all()
    )

    return [member.citizen_id for member in members]


def get_cluster_info(db: Session, citizen_id: int) -> Optional[schemas.ClusterInfo]:
    """Get information about the cluster a citizen belongs to."""
    cluster_id = get_cluster_id_for_citizen(db, citizen_id)

    if not cluster_id:
        return None

    members = (
        db.query(models.AccountClusterMember)
        .filter(models.AccountClusterMember.cluster_id == cluster_id)
        .order_by(models.AccountClusterMember.created_at)
        .all()
    )

    return schemas.ClusterInfo(
        cluster_id=cluster_id,
        citizen_ids=[m.citizen_id for m in members],
        member_count=len(members),
        created_at=members[0].created_at if members else None,
    )


def add_citizen_to_cluster(db: Session, citizen_id: int, cluster_id: int):
    """Add a citizen to an existing cluster."""
    # Check if citizen is already in a cluster
    existing = (
        db.query(models.AccountClusterMember)
        .filter(models.AccountClusterMember.citizen_id == citizen_id)
        .first()
    )

    if existing:
        if existing.cluster_id == cluster_id:
            # Already in this cluster, nothing to do
            return
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Citizen {citizen_id} is already in cluster {existing.cluster_id}',
            )

    member = models.AccountClusterMember(cluster_id=cluster_id, citizen_id=citizen_id)
    db.add(member)
    db.commit()
    logger.info(f'Added citizen {citizen_id} to cluster {cluster_id}')


def get_next_cluster_id(db: Session) -> int:
    """Get the next available cluster ID."""
    max_id = db.query(func.max(models.AccountClusterMember.cluster_id)).scalar()
    return (max_id or 0) + 1


def merge_clusters(db: Session, keep_cluster_id: int, merge_cluster_id: int):
    """Merge two clusters into one."""
    if keep_cluster_id == merge_cluster_id:
        return  # Nothing to merge

    # Update all members from merge_cluster to keep_cluster
    db.query(models.AccountClusterMember).filter(
        models.AccountClusterMember.cluster_id == merge_cluster_id
    ).update({'cluster_id': keep_cluster_id})

    db.commit()
    logger.info(f'Merged cluster {merge_cluster_id} into cluster {keep_cluster_id}')


def initiate_link_request(
    db: Session, initiator_id: int, target_email: str
) -> schemas.ClusterJoinRequestResponse:
    """
    Initiate a request to link accounts.
    Sends verification code to target email.
    """
    # Find target citizen by email
    target = (
        db.query(Citizen).filter(Citizen.primary_email == target_email.lower()).first()
    )

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'No account found with email {target_email}',
        )

    if target.id == initiator_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Cannot link account to itself',
        )

    # Check if they're already in the same cluster
    initiator_cluster = get_cluster_id_for_citizen(db, initiator_id)
    target_cluster = get_cluster_id_for_citizen(db, target.id)

    if initiator_cluster and target_cluster and initiator_cluster == target_cluster:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Accounts are already linked',
        )

    # Get initiator's email
    initiator = db.query(Citizen).filter(Citizen.id == initiator_id).first()
    if not initiator:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Initiator not found',
        )
    initiator_email = initiator.primary_email

    # Generate verification code
    code = generate_verification_code()
    expiration = datetime.now(timezone.utc) + timedelta(minutes=15)

    # Create join request
    request = models.ClusterJoinRequest(
        initiator_citizen_id=initiator_id,
        target_citizen_id=target.id,
        verification_code=code,
        code_expiration=expiration,
        status='pending',
    )
    db.add(request)
    db.commit()
    db.refresh(request)

    # Send verification email
    try:
        email_log.send_mail(
            receiver_mail=target_email,
            event=EmailEvent.LINK_ACCOUNTS_VERIFICATION.value,
            params={
                'verification_code': code,
                'email': target_email,
                'initiator_email': initiator_email,
                'contact_email': 'info@edgecity.live',
            },
            entity_type='cluster_join_request',
            entity_id=request.id,
        )
        logger.info(
            'Sent cluster join verification email to %s for request %s',
            target_email,
            request.id,
        )
    except Exception as e:
        logger.error('Failed to send verification email: %s', str(e))
        # Delete the request since we couldn't send the email
        db.delete(request)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Failed to send verification email to {target_email}. Please try again later.',
        )

    return schemas.ClusterJoinRequestResponse(
        message=f'Verification code sent to {target_email}',
        request_id=request.id,
    )


def verify_and_complete_link(
    db: Session, verification_code: str, current_user_id: int
) -> schemas.VerifyJoinResponse:
    """
    Verify the code and complete the account linking.
    Merges accounts into a cluster.
    """
    # Find the pending request
    request = (
        db.query(models.ClusterJoinRequest)
        .filter(
            models.ClusterJoinRequest.verification_code == verification_code,
            models.ClusterJoinRequest.status == 'pending',
        )
        .first()
    )

    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Invalid verification code',
        )

    # Check expiration
    if datetime.now(timezone.utc) > request.code_expiration:
        request.status = 'expired'
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Verification code has expired',
        )

    initiator_id = request.initiator_citizen_id
    target_id = request.target_citizen_id

    # SECURITY: Only the initiator can verify the code
    if current_user_id != initiator_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Only the account that initiated the link request can verify the code',
        )

    # Get existing clusters
    initiator_cluster = get_cluster_id_for_citizen(db, initiator_id)
    target_cluster = get_cluster_id_for_citizen(db, target_id)

    if initiator_cluster and target_cluster:
        # Both in clusters - merge them
        if initiator_cluster != target_cluster:
            merge_clusters(db, initiator_cluster, target_cluster)
        cluster_id = initiator_cluster

    elif initiator_cluster:
        # Add target to initiator's cluster
        add_citizen_to_cluster(db, target_id, initiator_cluster)
        cluster_id = initiator_cluster

    elif target_cluster:
        # Add initiator to target's cluster
        add_citizen_to_cluster(db, initiator_id, target_cluster)
        cluster_id = target_cluster

    else:
        # Neither in cluster - create new one
        cluster_id = get_next_cluster_id(db)
        add_citizen_to_cluster(db, initiator_id, cluster_id)
        add_citizen_to_cluster(db, target_id, cluster_id)

    # Mark request as verified
    request.status = 'verified'
    db.commit()

    logger.info(
        f'Successfully linked citizens {initiator_id} and {target_id} in cluster {cluster_id}'
    )

    return schemas.VerifyJoinResponse(
        message='Accounts successfully linked', cluster_id=cluster_id
    )


def leave_cluster(db: Session, citizen_id: int) -> schemas.LeaveClusterResponse:
    """Remove a citizen from their cluster."""
    member = (
        db.query(models.AccountClusterMember)
        .filter(models.AccountClusterMember.citizen_id == citizen_id)
        .first()
    )

    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='You are not in any cluster',
        )

    cluster_id = member.cluster_id

    # Remove the member
    db.delete(member)
    db.commit()

    logger.info(f'Citizen {citizen_id} left cluster {cluster_id}')

    return schemas.LeaveClusterResponse(message='Successfully left the account cluster')


def cleanup_expired_requests(db: Session):
    """Mark expired pending requests as expired (maintenance task)."""
    now = datetime.now(timezone.utc)

    updated = (
        db.query(models.ClusterJoinRequest)
        .filter(
            models.ClusterJoinRequest.status == 'pending',
            models.ClusterJoinRequest.code_expiration < now,
        )
        .update({'status': 'expired'})
    )

    db.commit()

    if updated > 0:
        logger.info(f'Marked {updated} expired cluster join requests')

    return updated
