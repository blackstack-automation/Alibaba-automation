import os

basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-secure")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(basedir, "instance", "mail_dashboard.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
    SEND_RATE_LIMIT_PER_SECOND = int(os.environ.get("SEND_RATE_LIMIT_PER_SECOND", "5"))
    JOB_FAILURE_THRESHOLD_PERCENT = int(os.environ.get("JOB_FAILURE_THRESHOLD_PERCENT", "5"))
    WTF_CSRF_ENABLED = True


class DevConfig(Config):
    DEBUG = True


class ProdConfig(Config):
    DEBUG = False


config_by_name = {
    "development": DevConfig,
    "production": ProdConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "production")
    return config_by_name.get(env, ProdConfig)
