#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
静电薄膜电机文献库 · 检索工具
用法:
  python ask.py "thrust force density"              # 段落级检索(带出处)
  python ask.py "electret motor" -n 15              # 返回15条
  python ask.py "dual excitation" --tier 1          # 只在①核心里搜
  python ask.py --paper "Egawa"                     # 按标题/作者找论文
  python ask.py --stats                             # 库统计
FTS5 语法: 空格=AND, OR, NOT, "词组", 前缀*
"""
import sqlite3,sys,os,argparse,textwrap
DB=os.path.join(os.path.dirname(os.path.abspath(__file__)),"文献库索引.db")

def conn(): return sqlite3.connect(DB)

def search(q,n=8,tier=None):
    c=conn().cursor()
    sql="""SELECT ch.file,ch.page,snippet(chunks,2,'【','】','…',22),p.title,p.authors,p.year,p.venue,p.doi,p.tier
           FROM chunks ch JOIN papers p ON p.file=ch.file
           WHERE chunks MATCH ?"""
    args=[q]
    if tier:
        TM={"1":"①","2":"②","3":"③","4":"④"}
        t=TM.get(str(tier),str(tier))
        sql+=" AND p.tier LIKE ?"; args.append(f"%{t}%")
    sql+=" ORDER BY rank LIMIT ?"; args.append(n)
    rows=c.execute(sql,args).fetchall()
    if not rows:
        print("无命中。换个词试试，或用 OR 连接同义词。"); return
    print(f"\n=== 命中 {len(rows)} 段 ===\n")
    for i,(f,pg,sn,ti,au,yr,ve,doi,tr) in enumerate(rows,1):
        a=(au or "").split(",")[0]
        print(f"[{i}] {ti}")
        print(f"    {a} et al. ({yr}) · {ve} · {tr}")
        print(f"    DOI: {doi or '—'}   | 出处: 第{pg}页  | 文件: PDFs/00_film_motor_focus/{f}")
        print(textwrap.fill(sn.replace('\n',' '),width=96,initial_indent="    > ",subsequent_indent="      "))
        print()

def paper(kw):
    c=conn().cursor()
    rows=c.execute("""SELECT title,authors,year,venue,doi,tier,cited,file FROM papers
       WHERE title LIKE ? OR authors LIKE ? ORDER BY cited DESC LIMIT 20""",(f"%{kw}%",f"%{kw}%")).fetchall()
    for ti,au,yr,ve,doi,tr,ct,f in rows:
        print(f"· ({yr}) {ti}\n    {(au or '')[:70]} | {ve} | 被引{ct} | {tr}\n    DOI:{doi or '—'} | {f}\n")
    print(f"共 {len(rows)} 篇")

def stats():
    c=conn().cursor()
    print("论文数:",c.execute("SELECT COUNT(*) FROM papers").fetchone()[0])
    print("段落数:",c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    for t,n in c.execute("SELECT tier,COUNT(*) FROM papers GROUP BY tier ORDER BY n DESC" if False else "SELECT tier,COUNT(*) c FROM papers GROUP BY tier ORDER BY c DESC"):
        print(f"  {t}: {n}")
    print("年份:",*c.execute("SELECT MIN(year),MAX(year) FROM papers WHERE year>1900").fetchone())

if __name__=="__main__":
    ap=argparse.ArgumentParser(add_help=False)
    ap.add_argument("query",nargs="*")
    ap.add_argument("-n",type=int,default=8)
    ap.add_argument("--tier",default=None)
    ap.add_argument("--paper",default=None)
    ap.add_argument("--stats",action="store_true")
    a=ap.parse_args()
    if a.stats: stats()
    elif a.paper: paper(a.paper)
    elif a.query: search(" ".join(a.query),a.n,a.tier)
    else: print(__doc__)
