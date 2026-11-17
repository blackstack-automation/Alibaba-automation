import click

from app.extensions import db
from app.models.user import User


def register_cli(app):
    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--password", required=True)
    @click.option("--role", default="admin", type=click.Choice(["admin", "operator"]))
    def create_admin(email, password, role):
        """Create (or update the password of) an admin/operator user."""
        email = email.lower().strip()
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(password)
            user.role = role
            db.session.commit()
            click.echo(f"Updated existing user {email}.")
            return

        user = User(email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created user {email}.")
