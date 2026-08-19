"""最初の Organization と運営者を用意するためのCLI。

通常の会社追加はUI（運営者の「会社」タブ）で行う。ここが残っているのは、
最初の運営者を作る手段が他に無いため（鶏と卵）。

使い方（backendディレクトリで）:
  poetry run python -m app.cli create-org --name "会社名" --code ykr --group "一般" \
      --admin-username admin --admin-name "管理者 太郎" --provider-operator
  poetry run python -m app.cli grant-provider --company-code ykr --username bcman

パスワードはここでは決めない。印刷される招待リンクを本人が開いて自分で設定する
（docs/identity/CONTEXT.md の Invitation）。
"""
import argparse
import re
import sys

from . import auth
from .database import Base, SessionLocal, engine
from .invitations import issue_invitation
from .models import Group, Organization, User, UserGroup
from .schemas import COMPANY_CODE_PATTERN, normalize_company_code


def _company_code(value: str) -> str:
    normalized = normalize_company_code(value)
    if not re.fullmatch(COMPANY_CODE_PATTERN, normalized):
        raise argparse.ArgumentTypeError("会社コードは英小文字・数字・ハイフンの3〜20文字です")
    return normalized


def _print_invitation(issued: dict) -> None:
    print(f"招待リンク（24時間有効・一回限り）:\n  {issued['invitation_url']}")
    # 公開URLの設定を誤っていてもトークンからURLを組み直せるように、生の値も出す
    print(f"トークン: {issued['invitation_url'].rsplit('/', 1)[-1]}")
    try:
        import qrcode

        qr = qrcode.QRCode()
        qr.add_data(issued["invitation_url"])
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        pass


def create_org(args: argparse.Namespace) -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(Organization).filter_by(code=args.code).first():
            sys.exit(f"会社コード '{args.code}' は既に使われています")
        if db.query(Organization).filter_by(name=args.name).first():
            sys.exit(f"会社名 '{args.name}' は既に登録されています")

        org = Organization(name=args.name, code=args.code, sharing_mode=args.sharing_mode)
        db.add(org); db.flush()
        group = Group(organization_id=org.id, name=args.group)
        db.add(group); db.flush()
        admin = User(
            organization_id=org.id, username=args.admin_username, name=args.admin_name,
            role="admin", is_provider_operator=args.provider_operator,
            password_hash="", totp_secret="", activated_at=None,
        )
        db.add(admin); db.flush()
        db.add(UserGroup(user_id=admin.id, group_id=group.id))
        # 発行者が他にいないので自分自身を発行者として記録する
        issued = issue_invitation(db, admin, admin)
        db.commit()

        print(f"作成しました: {org.name}（会社コード {org.code}） / 管理者 {admin.username}")
        if args.provider_operator:
            print("この管理者には運営者権限を付けました。")
        _print_invitation(issued)


def grant_provider(args: argparse.Namespace) -> None:
    """既存アカウントへ運営者権限を与える。

    bootstrap() でユーザー名を見て自動付与してはいけない（無関係な改名で
    別アカウントへ権限が滑る）。明示的な手順として残す。
    """
    with SessionLocal() as db:
        org = db.query(Organization).filter_by(code=args.company_code).first()
        if not org:
            sys.exit(f"会社コード '{args.company_code}' が見つかりません")
        user = db.query(User).filter_by(organization_id=org.id, username=args.username).first()
        if not user:
            sys.exit(f"'{args.username}' が {org.name} に見つかりません")
        user.is_provider_operator = True
        db.commit()
        print(f"{org.name} の {user.username} に運営者権限を付けました")


def reinvite(args: argparse.Namespace) -> None:
    """UIへ入れなくなったときの最後の手段。"""
    with SessionLocal() as db:
        org = db.query(Organization).filter_by(code=args.company_code).first()
        if not org:
            sys.exit(f"会社コード '{args.company_code}' が見つかりません")
        user = db.query(User).filter_by(organization_id=org.id, username=args.username).first()
        if not user:
            sys.exit(f"'{args.username}' が {org.name} に見つかりません")
        issued = issue_invitation(db, user, user)
        db.commit()
        print(f"{org.name} の {user.username} を招待し直しました")
        _print_invitation(issued)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-org", help="Organization・初期Group・初期管理者を作成する")
    create.add_argument("--name", required=True, help="Organization名")
    create.add_argument("--code", required=True, type=_company_code, help="会社コード（作成後は変更できない）")
    create.add_argument("--sharing-mode", default="isolated", choices=["isolated", "shared"])
    create.add_argument("--group", required=True, help="初期Group名")
    create.add_argument("--admin-username", required=True, help="初期管理者のログインID")
    create.add_argument("--admin-name", required=True, help="初期管理者の表示名")
    create.add_argument("--provider-operator", action="store_true", help="運営者権限も与える")
    create.set_defaults(func=create_org)

    grant = subparsers.add_parser("grant-provider", help="既存アカウントへ運営者権限を与える")
    grant.add_argument("--company-code", required=True, type=_company_code)
    grant.add_argument("--username", required=True)
    grant.set_defaults(func=grant_provider)

    invite = subparsers.add_parser("reinvite", help="招待し直す（UIへ入れなくなったときの最後の手段）")
    invite.add_argument("--company-code", required=True, type=_company_code)
    invite.add_argument("--username", required=True)
    invite.set_defaults(func=reinvite)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
