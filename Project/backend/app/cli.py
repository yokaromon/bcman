"""Organization・初期管理者の作成はUIを持たず、このCLIで行う（Q6: docs/identity/CONTEXT.md）。
使い方（backendディレクトリで）:
  poetry run python -m app.cli create-org --name "会社名" --group "一般" \
      --admin-username admin --admin-name "管理者 太郎"
パスワードを引数で渡さなければ、シェル履歴に残らないようその場で入力を求める。
"""
import argparse
import getpass
import sys

from . import auth
from .database import Base, SessionLocal, engine
from .models import Group, Organization, User, UserGroup


def create_org(args: argparse.Namespace) -> None:
    Base.metadata.create_all(engine)
    password = args.admin_password or getpass.getpass("初期管理者のパスワード（12文字以上）: ")
    with SessionLocal() as db:
        if db.query(User).filter_by(username=args.admin_username).first():
            sys.exit(f"ID '{args.admin_username}' は既に使われています")
        org = Organization(name=args.name, sharing_mode=args.sharing_mode)
        db.add(org); db.flush()
        group = Group(organization_id=org.id, name=args.group)
        db.add(group); db.flush()
        secret = auth.generate_totp_secret()
        admin = User(
            organization_id=org.id, username=args.admin_username, name=args.admin_name,
            role="admin", password_hash=auth.hash_password(password), totp_secret=secret,
        )
        db.add(admin); db.flush()
        db.add(UserGroup(user_id=admin.id, group_id=group.id))
        db.commit()
        uri = auth.totp_provisioning_uri(secret, admin.username)
        print(f"作成しました: Organization={org.name} ({org.id}) / Group={group.name} ({group.id}) / 管理者={admin.username} ({admin.id})")
        print(f"認証アプリへの登録用URI（この画面以外には残らないので今すぐ設定してください）:\n  {uri}")
        try:
            import qrcode
            qr = qrcode.QRCode()
            qr.add_data(uri)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-org", help="Organization・初期Group・初期管理者を作成する")
    create.add_argument("--name", required=True, help="Organization名")
    create.add_argument("--sharing-mode", default="isolated", choices=["isolated", "shared"])
    create.add_argument("--group", required=True, help="初期Group名")
    create.add_argument("--admin-username", required=True, help="初期管理者のログインID")
    create.add_argument("--admin-name", required=True, help="初期管理者の表示名")
    create.add_argument("--admin-password", default=None, help="省略時はその場で入力を求める")
    create.set_defaults(func=create_org)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
