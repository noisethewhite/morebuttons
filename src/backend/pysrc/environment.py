from .envenum import EnvEnum


class Environment(EnvEnum):
    shopify_api_key     = "SHOPIFY_API_KEY"
    shopify_secret      = "SHOPIFY_SECRET"
    shopify_api_version = "SHOPIFY_API_VERSION"
    database_url        = "DATABASE_URL"
    flask_secret_key    = "FLASK_SECRET_KEY"
    public_app_url      = "SHOPIFY_APP_URL"
