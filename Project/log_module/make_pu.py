"""
logs.db → logs.pu（PlantUML シーケンス図）を生成する。

使い方:
    python make_pu.py
    python make_pu.py --db path/to/logs.db --out path/to/output.pu
"""

import argparse
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DEFAULT_DB  = SCRIPT_DIR / 'logs.db'
DEFAULT_OUT = SCRIPT_DIR / 'logs.pu'

ARROW = ' -> '


def fetch_rows(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        'SELECT id, timestamp, from_node, to_node, source_file, line_no, message '
        'FROM logs '
        'WHERE from_node IS NOT NULL AND to_node IS NOT NULL '
        'ORDER BY id'
    ).fetchall()
    conn.close()
    return rows


def build_pu(rows: list[tuple]) -> str:
    # 登場順に participants を収集
    seen: list[str] = []
    for _id, _ts, fn, tn, _sf, _ln, _msg in rows:
        for nd in (fn, tn):
            if nd not in seen:
                seen.append(nd)

    first_ts = rows[0][1][:19].replace('T', ' ')
    last_ts  = rows[-1][1][:19].replace('T', ' ')

    lines: list[str] = [
        '@startuml',
        '',
        f'title EC Shop Log Sequence\\n{first_ts} - {last_ts}',
        '',
        'skinparam sequenceMessageAlign left',
        'skinparam maxMessageSize 300',
        'autonumber',
        '',
    ]

    for p in seen:
        lines.append(f'participant "{p}" as {p}')
    lines.append('')

    for _id, _ts, fn, tn, sf, ln, msg in rows:
        msg_clean = msg.replace('"', "'")
        lines.append(f'{fn}{ARROW}{tn} : {msg_clean}')
        if sf and ln:
            lines.append(f'note right: {sf}:{ln}')

    lines += ['', '@enduml', '']
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description='logs.db → PlantUML sequence diagram')
    parser.add_argument('--db',  default=str(DEFAULT_DB),  help='入力 SQLite DB')
    parser.add_argument('--out', default=str(DEFAULT_OUT), help='出力 .pu ファイル')
    args = parser.parse_args()

    db_path  = Path(args.db)
    out_path = Path(args.out)

    if not db_path.exists():
        print(f'[ERROR] DB が見つかりません: {db_path}', file=sys.stderr)
        sys.exit(1)

    rows = fetch_rows(db_path)
    if not rows:
        print('from_node/to_node が設定されたログがありません', file=sys.stderr)
        sys.exit(0)

    pu_text = build_pu(rows)
    out_path.write_text(pu_text, encoding='utf-8')
    print(f'生成完了: {out_path} ({len(rows)} エントリ)')


if __name__ == '__main__':
    main()
