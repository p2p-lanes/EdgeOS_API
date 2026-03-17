import os
from enum import Enum

from dotenv import load_dotenv

load_dotenv()


class Environment(str, Enum):
    TEST = 'test'
    PRODUCTION = 'production'
    DEVELOP = 'develop'


class Settings:
    ENVIRONMENT: Environment = Environment(os.getenv('ENVIRONMENT') or Environment.TEST)
    DB_USERNAME: str = os.getenv('DB_USERNAME', '')
    DB_PASSWORD: str = os.getenv('DB_PASSWORD', '')
    DB_HOST: str = os.getenv('DB_HOST', '')
    DB_PORT: str = os.getenv('DB_PORT', '')
    DB_NAME: str = os.getenv('DB_NAME', '')

    SQLALCHEMY_TEST_DATABASE_URL = 'sqlite:///:memory:'
    DATABASE_URL: str = (
        f'postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
        if ENVIRONMENT != Environment.TEST
        else SQLALCHEMY_TEST_DATABASE_URL
    )

    POSTMARK_API_TOKEN: str = os.getenv('POSTMARK_API_TOKEN', '')
    EMAIL_FROM_ADDRESS: str = os.getenv('EMAIL_FROM_ADDRESS', '')
    EMAIL_FROM_NAME: str = os.getenv('EMAIL_FROM_NAME', '')
    EMAIL_REPLY_TO: str = os.getenv('EMAIL_REPLY_TO', '')

    SECRET_KEY: str = os.getenv('SECRET_KEY', '')
    BACKEND_URL: str = os.getenv('BACKEND_URL', '')
    FRONTEND_URL: str = os.getenv('FRONTEND_URL', '')
    WORLD_EDGE_APP_ID: str = os.getenv('WORLD_EDGE_APP_ID', '')
    WORLD_EDGE_APP_TOKEN: str = os.getenv('WORLD_EDGE_APP_TOKEN', '')
    WORLD_APP_URL: str = os.getenv('WORLD_APP_URL', '')
    SIMPLEFI_API_URL: str = os.getenv('SIMPLEFI_API_URL', '')
    NOCODB_URL: str = os.getenv('NOCODB_URL', '')
    NOCODB_TOKEN: str = os.getenv('NOCODB_TOKEN', '')
    NOCODB_WEBHOOK_SECRET: str = os.getenv('NOCODB_WEBHOOK_SECRET', '')
    COUPON_API_KEY: str = os.getenv('COUPON_API_KEY', '')
    ATTENDEES_MANAGEMENT_API_KEY: str = os.getenv('ATTENDEES_MANAGEMENT_API_KEY', '')
    ATTENDEES_API_KEY: str = os.getenv('ATTENDEES_API_KEY', '')
    ATTENDEES_TICKETS_API_KEY: str = os.getenv('ATTENDEES_TICKETS_API_KEY', '')
    ATTENDEES_TICKETS_API_KEY_2: str = os.getenv('ATTENDEES_TICKETS_API_KEY_2', '')
    GROUPS_API_KEY: str = os.getenv('GROUPS_API_KEY', '')
    API_KEY_WORLD_ADDRESSES: str = os.getenv('API_KEY_WORLD_ADDRESSES', '')
    CHECK_IN_API_KEY: str = os.getenv('CHECK_IN_API_KEY', '')
    WORLD_BUILDERS_API_KEY: str = os.getenv('WORLD_BUILDERS_API_KEY', '')
    WORLD_CHAIN_URL: str = os.getenv('WORLD_CHAIN_URL', '')
    WORLD_LOGIN_MESSAGE_HASH: str = os.getenv('WORLD_LOGIN_MESSAGE_HASH', '')

    APPLICATIONS_TABLE_ID: str = os.getenv('APPLICATIONS_TABLE_ID', '')
    APPLICATIONS_API_KEY: str = os.getenv('APPLICATIONS_API_KEY', '')

    POAP_API_KEY: str = os.getenv('POAP_API_KEY', '')
    POAP_CLIENT_ID: str = os.getenv('POAP_CLIENT_ID', '')
    POAP_CLIENT_SECRET: str = os.getenv('POAP_CLIENT_SECRET', '')

    REMINDER_EMAILS_API_KEY: str = os.getenv('REMINDER_EMAILS_API_KEY', '')

    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID: str = os.getenv('TELEGRAM_CHAT_ID', '')
    TELEGRAM_MESSAGE_THREAD_ID: str = os.getenv('TELEGRAM_MESSAGE_THREAD_ID', '')

    HASURA_URL: str = os.getenv('HASURA_URL', '')

    GEMINI_API_KEY: str = os.getenv('GEMINI_API_KEY', '')
    EDGECLAW_API_KEY: str = os.getenv('EDGECLAW_API_KEY', '')

    MAX_ALLOWED_INSTALLMENTS: int = int(os.getenv('MAX_ALLOWED_INSTALLMENTS', '6'))

    # x402
    X402_FACILITATOR_URL: str = os.getenv(
        'X402_FACILITATOR_URL', 'https://api.cdp.coinbase.com/platform/v2/x402'
    )
    X402_NETWORK: str = os.getenv('X402_NETWORK', 'eip155:8453')
    X402_USDC_ADDRESS: str = os.getenv(
        'X402_USDC_ADDRESS', '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'
    )
    X402_PAY_TO: str = os.getenv('X402_PAY_TO', '')
    X402_MAX_TIMEOUT: int = int(os.getenv('X402_MAX_TIMEOUT', '60'))

    # AgentKit on Base chain
    AGENTKIT_AGENTBOOK_ADDRESS: str = os.getenv(
        'AGENTKIT_AGENTBOOK_ADDRESS', '0xE1D1D3526A6FAa37eb36bD10B933C1b77f4561a4'
    )
    AGENTKIT_RPC_URL: str = os.getenv('AGENTKIT_RPC_URL', 'https://mainnet.base.org')
    AGENTKIT_DISCOUNT_PERCENT: int = int(os.getenv('AGENTKIT_DISCOUNT_PERCENT', '10'))


settings = Settings()
