from datetime import datetime, timedelta
from pathlib import Path
import shutil
import uuid
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form
from pydantic import BaseModel
import json
import re
from sqlalchemy import create_engine, String, Text, ForeignKey, DateTime, Integer, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

engine = create_engine("sqlite:///guozi.db")
class Base(DeclarativeBase): pass
now = datetime.utcnow
class Tree(Base):
    __tablename__ = "trees"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_public: Mapped[int] = mapped_column(Integer, default=0)
    show_dead: Mapped[int] = mapped_column(Integer, default=1)
    text_attachments_only: Mapped[int] = mapped_column(Integer, default=1)
    forked_from: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    forked_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    forked_owner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    decorations: Mapped[str] = mapped_column(Text, default="[]")  # JSON list: whitewash|rope|nameplate
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_grown_at: Mapped[datetime] = mapped_column(DateTime, default=now)
class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    tree_id: Mapped[int] = mapped_column(ForeignKey("trees.id"))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(10), default="bud")
    ripeness: Mapped[str] = mapped_column(String(20), default="none")  # none|green|swelling|coloring|ripe
    source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # ai|example|null
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    layout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: tx/ty/curve/side 归一化
    role: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # idea|stage|approach|null
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # pending|active|done|stuck（仅 stage）
    is_demo: Mapped[int] = mapped_column(Integer, default=0)  # 1=示例/测试数据，正式视图默认隐藏
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"))
    kind: Mapped[str] = mapped_column(String(20), default="file")  # text|image|file
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    nickname: Mapped[str] = mapped_column(String(50))
    avatar: Mapped[str] = mapped_column(String(20), default="pinecone")
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, unique=True)
    pw_hash: Mapped[str] = mapped_column(String(200))
    agreed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    agreement_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

Base.metadata.create_all(engine)
with engine.begin() as conn:
    cols_n = {r[1] for r in conn.execute(text("PRAGMA table_info(nodes)"))}
    if "ripeness" not in cols_n:
        conn.execute(text("ALTER TABLE nodes ADD COLUMN ripeness VARCHAR(20) DEFAULT 'none'"))
        conn.execute(text("UPDATE nodes SET ripeness='ripe' WHERE state='fruit' AND (ripeness IS NULL OR ripeness='none')"))
    cols_t = {r[1] for r in conn.execute(text("PRAGMA table_info(trees)"))}
    if "decorations" not in cols_t:
        conn.execute(text("ALTER TABLE trees ADD COLUMN decorations TEXT DEFAULT '[]'"))
    cols_n2 = {r[1] for r in conn.execute(text("PRAGMA table_info(nodes)"))}
    if "layout" not in cols_n2:
        conn.execute(text("ALTER TABLE nodes ADD COLUMN layout TEXT"))
    cols_n3 = {r[1] for r in conn.execute(text("PRAGMA table_info(nodes)"))}
    if "role" not in cols_n3:
        conn.execute(text("ALTER TABLE nodes ADD COLUMN role VARCHAR(20)"))
    if "sort_order" not in cols_n3:
        conn.execute(text("ALTER TABLE nodes ADD COLUMN sort_order INTEGER DEFAULT 0"))
    if "progress" not in cols_n3:
        conn.execute(text("ALTER TABLE nodes ADD COLUMN progress VARCHAR(20)"))
    cols_n4 = {r[1] for r in conn.execute(text("PRAGMA table_info(nodes)"))}
    if "is_demo" not in cols_n4:
        conn.execute(text("ALTER TABLE nodes ADD COLUMN is_demo INTEGER DEFAULT 0"))
STATES = {"bud", "leaf", "fruit", "dead"}
RIPENESS = {"none", "green", "swelling", "coloring", "ripe"}
RIPENESS_MANUAL = {"green", "swelling", "coloring"}  # ripe 只能走 complete
DECORATIONS = {"whitewash", "rope", "nameplate"}
ROLES = {"idea", "stage", "approach"}
PROGRESS = {"pending", "active", "done", "stuck"}
DEMO_TITLE_RE = re.compile(r"(round\d+|ripeness-smoke|smoke|示例)", re.I)
app = FastAPI(title="让果子熟 API")
UPLOAD_DIR = Path("uploads"); UPLOAD_DIR.mkdir(exist_ok=True)

def ser_att(a):
    storage = a.url  # 磁盘文件名或空
    auth_url = f"/api/v1/attachments/{a.id}/file" if storage else None
    previewable = a.kind in {"image", "pdf", "text", "code"} or (storage or "").lower().endswith((".png",".jpg",".jpeg",".gif",".webp",".pdf",".txt",".md",".py",".js",".ts",".json",".html",".css"))
    return dict(id=a.id, node_id=a.node_id, kind=a.kind, name=a.name, url=auth_url, text=a.text,
                previewable=bool(previewable and (auth_url or a.text)),
                preview_url=auth_url if (previewable and auth_url) else None,
                created_at=a.created_at.isoformat()+"Z")
def _decorations(t):
    raw = getattr(t, "decorations", None) or "[]"
    try:
        v = json.loads(raw) if isinstance(raw, str) else list(raw)
    except Exception:
        v = []
    return [x for x in v if x in DECORATIONS]

def _layout(n):
    raw = getattr(n, "layout", None)
    if not raw: return None
    try:
        v = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        return None
    if not isinstance(v, dict): return None
    out = {}
    for k in ("tx", "ty", "curve"):
        if k in v and v[k] is not None:
            try: out[k] = float(v[k])
            except (TypeError, ValueError): pass
    if v.get("side") in ("left", "right"): out["side"] = v["side"]
    return out or None

def _role_of(n, s=None):
    r = getattr(n, "role", None)
    if r in ROLES: return r
    if n.parent_id is None: return None
    if s is None: return None
    par = s.get(Node, n.parent_id)
    if not par: return None
    if par.parent_id is None: return "idea"
    # 父是 idea → 默认当 stage；父是 stage → approach
    pr = _role_of(par, s)
    if pr == "idea": return "stage"
    if pr == "stage": return "approach"
    return None

def _stages_of_idea(s, idea_id):
    kids = s.query(Node).filter_by(parent_id=idea_id).all()
    stages = [k for k in kids if _role_of(k, s) == "stage"]
    stages.sort(key=lambda x: (getattr(x, "sort_order", 0) or 0, x.id))
    return stages

def _ensure_stage_progress(s, idea_id):
    """保证一枝最多一个 active；若全无 active 且有 pending，把第一个 pending 升为 active。"""
    stages = _stages_of_idea(s, idea_id)
    if not stages: return
    for st in stages:
        if not getattr(st, "progress", None):
            st.progress = "pending"
    actives = [st for st in stages if st.progress == "active"]
    if len(actives) > 1:
        for st in actives[1:]:
            st.progress = "pending"
    elif len(actives) == 0:
        pend = [st for st in stages if st.progress == "pending"]
        if pend and not all(st.progress == "done" for st in stages):
            # 若有 done 前缀，激活第一个 pending；否则激活第一个
            first_pending = next((st for st in stages if st.progress == "pending"), None)
            if first_pending: first_pending.progress = "active"

def _set_stage_progress(s, stage, progress):
    if _role_of(stage, s) != "stage":
        raise HTTPException(400, {"code": "NOT_STAGE", "msg": "只有环节点（stage）能改 progress"})
    if progress not in PROGRESS:
        raise HTTPException(400, "progress 只能是 pending/active/done/stuck")
    idea_id = stage.parent_id
    stages = _stages_of_idea(s, idea_id)
    if progress == "active":
        for st in stages:
            if st.id == stage.id: continue
            if st.progress == "active":
                st.progress = "pending"
        stage.progress = "active"
    elif progress == "done":
        stage.progress = "done"
        nxt = None
        for i, st in enumerate(stages):
            if st.id == stage.id and i + 1 < len(stages):
                nxt = stages[i + 1]; break
        others_active = any(st.progress == "active" and st.id != stage.id for st in stages)
        # 下一环若是 stuck/pending 且无其它 active，则激活（done/stuck 保持）
        if nxt and nxt.progress not in ("done",) and not others_active:
            if nxt.progress != "stuck":
                nxt.progress = "active"
        # 若全部 done，保持全绿无 active
    elif progress == "stuck":
        # stuck 不算 active，不挤掉其它 active
        stage.progress = "stuck"
    else:  # pending ——「取消卡住」等回到待做
        stage.progress = "pending"
        _ensure_stage_progress(s, idea_id)

def _title_looks_demo(title: str) -> bool:
    return bool(DEMO_TITLE_RE.search(title or ""))

def _backfill_demo_flags(s, tree_id):
    for n in s.query(Node).filter_by(tree_id=tree_id).all():
        if _title_looks_demo(n.title) and not getattr(n, "is_demo", 0):
            n.is_demo = 1
    # 想法枝若自身或任一子树标题命中，整枝标 demo（含子孙）
    trunk = _trunk(s, tree_id)
    if not trunk: return
    ideas = s.query(Node).filter_by(tree_id=tree_id, parent_id=trunk.id).all()
    for idea in ideas:
        subtree = [idea]
        # BFS
        i = 0
        while i < len(subtree):
            kids = s.query(Node).filter_by(parent_id=subtree[i].id).all()
            subtree.extend(kids); i += 1
        if any(getattr(x, "is_demo", 0) or _title_looks_demo(x.title) for x in subtree):
            for x in subtree:
                x.is_demo = 1

def _demo_ids_to_hide(s, tree_id):
    """正式视图隐藏：is_demo 节点，及其作为 demo 想法枝下的全部子孙。"""
    hide = set()
    for n in s.query(Node).filter_by(tree_id=tree_id).all():
        if getattr(n, "is_demo", 0):
            hide.add(n.id)
    # 再把 parent 在 hide 里的也藏掉（防漏标）
    changed = True
    nodes = s.query(Node).filter_by(tree_id=tree_id).all()
    while changed:
        changed = False
        for n in nodes:
            if n.id not in hide and n.parent_id in hide:
                hide.add(n.id); changed = True
    return hide

def ser_node(n, s=None):
    ripeness = getattr(n, "ripeness", None) or "none"
    is_trunk = n.parent_id is None
    role = _role_of(n, s)
    if role == "idea":
        is_idea = True
    elif role in ("stage", "approach"):
        is_idea = False
    else:
        is_idea = False
        if s is not None and n.parent_id is not None:
            par = s.get(Node, n.parent_id)
            is_idea = bool(par and par.parent_id is None)
    prog = getattr(n, "progress", None) if role == "stage" else None
    d = dict(id=n.id, tree_id=n.tree_id, parent_id=n.parent_id, is_seed=is_trunk, is_trunk=is_trunk, is_idea=is_idea,
             role=role, sort_order=int(getattr(n, "sort_order", 0) or 0), progress=prog,
             is_demo=bool(getattr(n, "is_demo", 0)),
             title=n.title, body=n.body, state=n.state, ripeness=ripeness, source=n.source, note=n.note, link=n.link,
             layout=_layout(n), updated_at=n.updated_at.isoformat()+"Z", attachment_count=0)
    if s is not None:
        atts = s.query(Attachment).filter_by(node_id=n.id).all()
        d["attachments"] = [ser_att(a) for a in atts]
        d["attachment_count"] = len(atts)
    return d

def _trunk(s, tree_id):
    return s.query(Node).filter_by(tree_id=tree_id, parent_id=None).order_by(Node.id).first()

def _merge_extra_trees(s, keep, extras):
    """把同用户其它树并入 keep：原树根降为一级想法枝。"""
    keep_root = _trunk(s, keep.id)
    if not keep_root:
        keep_root = Node(tree_id=keep.id, title="树干", body="", state="bud", ripeness="none")
        s.add(keep_root); s.flush()
    for et in extras:
        if et.is_public: keep.is_public = 1
        if et.last_grown_at and (not keep.last_grown_at or et.last_grown_at > keep.last_grown_at):
            keep.last_grown_at = et.last_grown_at
        # 装饰并集
        dec = list(dict.fromkeys(_decorations(keep) + _decorations(et)))
        keep.decorations = json.dumps(dec, ensure_ascii=False)
        roots = s.query(Node).filter_by(tree_id=et.id, parent_id=None).all()
        for r in roots:
            r.parent_id = keep_root.id
            r.layout = None  # 迁入用默认垂柳排布
            if r.title in ("种子", "树干") and et.title:
                r.title = et.title[:200]
        for n in s.query(Node).filter_by(tree_id=et.id).all():
            n.tree_id = keep.id
        s.query(Tree).filter_by(forked_from=et.id).update({Tree.forked_from: keep.id}, synchronize_session=False)
        s.delete(et)
    s.flush()

def _backfill_roles(s, tree_id):
    """给旧数据补 role/progress：干下→idea，idea 下→stage，stage 下→approach。"""
    trunk = _trunk(s, tree_id)
    if not trunk: return
    ideas = s.query(Node).filter_by(tree_id=tree_id, parent_id=trunk.id).all()
    for idea in ideas:
        if not getattr(idea, "role", None): idea.role = "idea"
        kids = s.query(Node).filter_by(parent_id=idea.id).order_by(Node.id).all()
        # 仅把尚未有 approach 父的一级子当 stage（旧数据一级多为阶段）
        order = 0
        for k in kids:
            kr = getattr(k, "role", None)
            if kr == "approach": continue
            if not kr or kr == "stage":
                k.role = "stage"
                if getattr(k, "sort_order", None) is None or (k.sort_order == 0 and order > 0 and not kr):
                    pass
                if not kr:
                    k.sort_order = order
                order += 1
                # approach 孙节点
                for g in s.query(Node).filter_by(parent_id=k.id).all():
                    if not getattr(g, "role", None): g.role = "approach"
        _ensure_stage_progress(s, idea.id)

def ensure_my_tree(s, uid):
    """一人一树：没有则建；多棵则合并成最早那棵。"""
    trees = s.query(Tree).filter_by(owner_id=uid).order_by(Tree.id).all()
    if not trees:
        t = Tree(owner_id=uid, title="我的树", decorations=json.dumps(["whitewash"], ensure_ascii=False))
        s.add(t); s.flush()
        s.add(Node(tree_id=t.id, title="树干", body="", state="bud", ripeness="none")); s.flush()
        return t
    keep = trees[0]
    if len(trees) > 1:
        _merge_extra_trees(s, keep, trees[1:])
    if not _trunk(s, keep.id):
        s.add(Node(tree_id=keep.id, title="树干", body="", state="bud", ripeness="none")); s.flush()
    _backfill_roles(s, keep.id)
    _backfill_demo_flags(s, keep.id)
    return keep

def _copy_subtree_as_idea(s, src_tree_id, dest_tree, dest_parent_id, reset_grow=True):
    """把源树整棵（以原根为想法枝）挂到 dest_parent 下，返回新想法节点。"""
    nodes = s.query(Node).filter_by(tree_id=src_tree_id).all()
    by_id = {n.id: n for n in nodes}
    roots = [n for n in nodes if n.parent_id is None]
    if not roots:
        return None
    idmap = {}
    # 先按拓扑：根 → 子
    pending = list(nodes)
    guard = 0
    while pending and guard < 10000:
        guard += 1
        rest = []
        for n in pending:
            if n.parent_id is None:
                parent_new = dest_parent_id
            elif n.parent_id in idmap:
                parent_new = idmap[n.parent_id]
            else:
                rest.append(n); continue
            nn = Node(
                tree_id=dest_tree.id, parent_id=parent_new, title=n.title, body=n.body,
                state=("bud" if reset_grow else n.state),
                ripeness=("none" if reset_grow else (getattr(n, "ripeness", None) or "none")),
                source=n.source, note=(None if reset_grow else n.note), link=(None if reset_grow else n.link),
                layout=None,
            )
            # 原树根挂到本人树干下时，标题用源树名更像「一枝一想法」
            if n.parent_id is None and dest_tree.title and n.title in ("种子", "树干"):
                src_t = s.get(Tree, src_tree_id)
                if src_t and src_t.title: nn.title = src_t.title[:200]
            s.add(nn); s.flush(); idmap[n.id] = nn.id
            for a in s.query(Attachment).filter_by(node_id=n.id).all():
                s.add(Attachment(node_id=nn.id, kind=a.kind, name=a.name, url=a.url, text=a.text))
        if len(rest) == len(pending): break
        pending = rest
    root_src = roots[0]
    return s.get(Node, idmap.get(root_src.id))
def _fork_src(t, s):
    if not t.forked_from and not t.forked_title: return None
    o = s.get(Tree, t.forked_from) if t.forked_from else None
    oid = o.owner_id if o else t.forked_owner_id
    return dict(tree_id=t.forked_from, title=o.title if o else t.forked_title, owner_id=oid, author=_author(s, oid), available=bool(o and o.is_public))
def _author(s, uid):
    u = s.get(User, uid) if uid else None
    return dict(id=uid, nickname=u.nickname if u else f"#{uid}", avatar=u.avatar if u else None)
def ser_tree(t, s, hide_demo: bool = True):
    _backfill_demo_flags(s, t.id)
    nodes = s.query(Node).filter_by(tree_id=t.id).all()
    if hide_demo:
        hide = _demo_ids_to_hide(s, t.id)
        nodes = [n for n in nodes if n.id not in hide]
    return dict(id=t.id, title=t.title, source_url=t.source_url, is_public=bool(t.is_public), last_grown_at=t.last_grown_at.isoformat()+"Z",
                needs_water=now()-t.last_grown_at > timedelta(days=7), nodes=[ser_node(n, s) for n in nodes],
                owner_id=t.owner_id, author=_author(s, t.owner_id), show_dead=bool(t.show_dead), text_attachments_only=bool(t.text_attachments_only), decorations=_decorations(t), forked_from=_fork_src(t, s), fork_count=s.query(Tree).filter(Tree.forked_from==t.id, Tree.owner_id!=t.owner_id).count(),
                hide_demo=hide_demo)

class SeedIn(BaseModel):
    tweet_url: Optional[str] = None
    text: Optional[str] = None
    title: Optional[str] = None

@app.post("/api/v1/seeds/import")
def import_seed(p: SeedIn, x_user_id: int = Header(...)):
    """一人一树：在本人树上抽一根新想法枝，不再新建 Tree。"""
    text, author = p.text, None
    if p.tweet_url and not text:
        try:
            r = httpx.get("https://publish.twitter.com/oembed", params={"url": p.tweet_url, "omit_script": 1}, timeout=8)
            r.raise_for_status(); d = r.json()
            import re, html
            text = html.unescape(re.sub(r"<[^>]+>", " ", d.get("html", ""))).strip(); author = d.get("author_name")
        except Exception:
            raise HTTPException(422, {"code": "OEMBED_FAILED", "msg": "拿不到推文内容，请手动粘贴正文"})
    if not text: raise HTTPException(400, "需要 tweet_url 或 text")
    with Session(engine) as s:
        t = ensure_my_tree(s, x_user_id)
        trunk = _trunk(s, t.id)
        body = text + (f"\n— {author}" if author else "")
        idea = Node(tree_id=t.id, parent_id=trunk.id, title=(p.title or text[:40])[:200], body=body, state="bud", ripeness="none", role="idea", sort_order=0)
        s.add(idea); s.flush()
        for i, b in enumerate(["读懂", "动手试", "做出东西"]):
            prog = "active" if i == 0 else "pending"
            s.add(Node(tree_id=t.id, parent_id=idea.id, title=b, state="bud", ripeness="none", role="stage", sort_order=i, progress=prog))
        if p.tweet_url and not t.source_url: t.source_url = p.tweet_url
        t.last_grown_at = now()
        s.commit(); return ser_tree(t, s)

@app.get("/api/v1/me/tree")
def me_tree(x_user_id: int = Header(...), include_demo: bool = False):
    """默认隐藏示例数据；侧栏打开「示例数据」时传 include_demo=true。"""
    with Session(engine) as s:
        t = ensure_my_tree(s, x_user_id)
        s.commit()
        return ser_tree(t, s, hide_demo=not include_demo)

@app.get("/api/v1/trees/{tid}")
def get_tree(tid: int, include_demo: bool = False):
    with Session(engine) as s:
        t = s.get(Tree, tid)
        if not t: raise HTTPException(404)
        return ser_tree(t, s, hide_demo=not include_demo)

@app.get("/api/v1/trees")
def my_trees(x_user_id: int = Header(...), include_demo: bool = False):
    """兼容旧前端：一人一树，返回 0～1 棵。"""
    with Session(engine) as s:
        t = ensure_my_tree(s, x_user_id); s.commit()
        return [ser_tree(t, s, hide_demo=not include_demo)]

class NodeIn(BaseModel):
    parent_id: int; title: str; body: str = ""; from_suggestion: Optional[dict] = None
    role: Optional[str] = None  # idea|stage|approach，不传则按父节点推断
    sort_order: Optional[int] = None

@app.post("/api/v1/trees/{tid}/nodes")
def grow(tid: int, p: NodeIn, x_user_id: int = Header(...)):
    with Session(engine) as s:
        t = s.get(Tree, tid); par = s.get(Node, p.parent_id)
        if not t or t.owner_id != x_user_id: raise HTTPException(403)
        if not par or par.tree_id != tid: raise HTTPException(400, "parent 不在这棵树上")
        src = None
        fs = p.from_suggestion or {}
        if fs:
            if fs.get("generated_by") == "ai" or fs.get("mock") is False:
                src = "ai"
            else:
                src = "example"
        # 推断 role
        role = p.role
        if role is not None and role not in ROLES:
            raise HTTPException(400, "role 只能是 idea/stage/approach")
        if role is None:
            pr = _role_of(par, s)
            if par.parent_id is None: role = "idea"
            elif pr == "idea": role = "stage"
            elif pr == "stage": role = "approach"
            else: role = None
        sort_order = p.sort_order
        if sort_order is None and role == "stage":
            sibs = _stages_of_idea(s, par.id) if _role_of(par, s) == "idea" else []
            sort_order = (max([x.sort_order for x in sibs], default=-1) + 1) if sibs is not None else 0
        if sort_order is None: sort_order = 0
        progress = None
        if role == "stage":
            # 若该想法尚无 active，新环变 active，否则 pending
            stages = _stages_of_idea(s, par.id) if _role_of(par, s) == "idea" else []
            has_active = any(getattr(x, "progress", None) == "active" for x in stages)
            progress = "pending" if has_active else "active"
        n = Node(tree_id=tid, parent_id=p.parent_id, title=p.title, body=p.body or (fs.get("first_step") or ""),
                 source=src, role=role, sort_order=sort_order, progress=progress)
        s.add(n); t.last_grown_at = now(); s.commit(); return ser_node(n, s)

class StateIn(BaseModel):
    state: str; note: Optional[str] = None; link: Optional[str] = None
@app.patch("/api/v1/nodes/{nid}")
def set_state(nid: int, p: StateIn, x_user_id: int = Header(...)):
    if p.state not in STATES: raise HTTPException(400, "state 只能是 bud/leaf/fruit/dead")
    with Session(engine) as s:
        n = s.get(Node, nid)
        if not n or s.get(Tree, n.tree_id).owner_id != x_user_id: raise HTTPException(403)
        if p.state == "fruit":
            raise HTTPException(400, {"code": "FRUIT_VIA_COMPLETE", "msg": "请用完结/摘熟接口，不要直接改成果实状态"})
        prev = n.state
        n.state = p.state
        if p.note is not None: n.note = p.note
        if p.link is not None: n.link = p.link
        # 升到绿叶：自动挂青果；退回嫩芽：清空果
        if p.state == "leaf" and (getattr(n, "ripeness", None) or "none") == "none":
            n.ripeness = "green"
        if p.state == "bud":
            n.ripeness = "none"
        # 枯枝保留 ripeness，前端画皱缩果
        s.commit(); return ser_node(n, s)

class RipenessIn(BaseModel):
    ripeness: str

@app.patch("/api/v1/nodes/{nid}/ripeness")
def set_ripeness(nid: int, p: RipenessIn, x_user_id: int = Header(...)):
    if p.ripeness == "ripe":
        raise HTTPException(400, {"code": "RIPE_VIA_COMPLETE", "msg": "熟透请走完结/摘熟接口"})
    if p.ripeness not in RIPENESS_MANUAL:
        raise HTTPException(400, "ripeness 只能是 green/swelling/coloring（ripe 走 /complete）")
    with Session(engine) as s:
        n = s.get(Node, nid)
        if not n or s.get(Tree, n.tree_id).owner_id != x_user_id: raise HTTPException(403)
        if n.parent_id is None:
            raise HTTPException(400, {"code": "SEED_NO_FRUIT", "msg": "种子节点不能挂果"})
        if n.state == "bud":
            raise HTTPException(400, {"code": "NEED_LEAF", "msg": "先升到绿叶再调成熟度"})
        if n.state == "dead" and p.ripeness != (getattr(n, "ripeness", None) or "none"):
            # 枯枝可保留原果，但不推进成熟
            raise HTTPException(400, {"code": "DEAD_NO_RIPEN", "msg": "枯枝上的果不能再推进成熟"})
        n.ripeness = p.ripeness
        s.commit(); return ser_node(n, s)

class ProgressIn(BaseModel):
    progress: str  # pending|active|done|stuck

@app.patch("/api/v1/nodes/{nid}/progress")
def set_progress(nid: int, p: ProgressIn, x_user_id: int = Header(...)):
    """环节点进度：done 后自动激活下一环；也可手动把未完成环设为 active。"""
    with Session(engine) as s:
        n = s.get(Node, nid)
        if not n or s.get(Tree, n.tree_id).owner_id != x_user_id: raise HTTPException(403)
        # 若旧数据无 role，按位置补成 stage
        if _role_of(n, s) != "stage":
            # 允许显式补：父是 idea 时当 stage
            par = s.get(Node, n.parent_id) if n.parent_id else None
            if par and _role_of(par, s) == "idea":
                n.role = "stage"
            else:
                raise HTTPException(400, {"code": "NOT_STAGE", "msg": "只有环节点（stage）能改 progress"})
        _set_stage_progress(s, n, p.progress)
        s.commit()
        return ser_node(n, s)

class DecorationsIn(BaseModel):
    decorations: list[str]

@app.patch("/api/v1/trees/{tid}/decorations")
def set_decorations(tid: int, p: DecorationsIn, x_user_id: int = Header(...)):
    bad = [x for x in p.decorations if x not in DECORATIONS]
    if bad: raise HTTPException(400, f"未知装束: {bad}，可选 whitewash/rope/nameplate")
    with Session(engine) as s:
        t = s.get(Tree, tid)
        if not t or t.owner_id != x_user_id: raise HTTPException(403)
        # 去重保序
        seen=set(); out=[]
        for x in p.decorations:
            if x not in seen: seen.add(x); out.append(x)
        t.decorations = json.dumps(out, ensure_ascii=False)
        s.commit(); return ser_tree(t, s)

class LayoutIn(BaseModel):
    tx: Optional[float] = None
    ty: Optional[float] = None
    curve: Optional[float] = None
    side: Optional[str] = None
    clear: bool = False  # true 清空，前端回默认垂柳

@app.patch("/api/v1/nodes/{nid}/layout")
def set_layout(nid: int, p: LayoutIn, x_user_id: int = Header(...)):
    with Session(engine) as s:
        n = s.get(Node, nid)
        if not n or s.get(Tree, n.tree_id).owner_id != x_user_id: raise HTTPException(403)
        if n.parent_id is None:
            raise HTTPException(400, {"code": "TRUNK_NO_LAYOUT", "msg": "树干不用拖布局"})
        if p.clear:
            n.layout = None
        else:
            cur = _layout(n) or {}
            if p.tx is not None: cur["tx"] = max(0.0, min(1.0, float(p.tx)))
            if p.ty is not None: cur["ty"] = max(0.0, min(1.0, float(p.ty)))
            if p.curve is not None: cur["curve"] = float(p.curve)
            if p.side is not None:
                if p.side not in ("left", "right"):
                    raise HTTPException(400, "side 只能是 left/right")
                cur["side"] = p.side
            if not cur:
                raise HTTPException(400, "请至少传 tx/ty/curve/side，或 clear=true")
            n.layout = json.dumps(cur, ensure_ascii=False)
        s.commit(); return ser_node(n, s)

@app.get("/api/v1/market")
def market():
    with Session(engine) as s:
        out = []
        for t in s.query(Tree).filter_by(is_public=1):
            d = ser_tree(t, s)
            fruits = [n for n in d["nodes"] if n.get("ripeness")=="ripe"]
            d["cover"] = dict(title=t.title, fruit_count=len(fruits), harvest=(fruits[0]["note"] if fruits else None), free=True)
            out.append(d)
        return out

def path_ctx(s, n):
    path=[]; cur=n
    while cur: path.append(cur); cur=s.get(Node,cur.parent_id) if cur.parent_id else None
    sib=s.query(Node).filter(Node.parent_id==n.parent_id, Node.id!=n.id, Node.tree_id==n.tree_id).all() if n.parent_id else []
    return [dict(title=x.title,state=x.state) for x in reversed(path)], [dict(title=x.title,state=x.state,note=x.note) for x in sib]

def _filter_suggestions(items):
    words = [w.strip().lower() for w in Path(__file__).with_name("banned_words.txt").read_text().splitlines() if w.strip()]
    out=[]
    for it in items:
        blob = (it.get("direction","")+it.get("first_step","")).lower()
        if any(w in blob for w in words):
            continue
        out.append(it)
    return out

def _llm_suggest(path, siblings, title):
    key = Path(__file__).with_name(".llm_key").read_text().strip() if Path(__file__).with_name(".llm_key").exists() else os.environ.get("LLM_API_KEY","")
    if not key: raise HTTPException(503, {"code": "AI_UNAVAILABLE", "msg": "AI 暂时不可用，请稍后再试"})
    base = os.environ.get("LLM_BASE_URL","https://api.siliconflow.cn/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL","Qwen/Qwen2.5-7B-Instruct")
    dead = [f"{x['title']}（原因：{x.get('note') or '未写'}）" for x in siblings if x["state"]=="dead"]
    prompt = ("你是学习路径教练。根据从种子到当前节点的路径，以及同级分叉（含已放弃的枯枝），给出 2 到 3 个下一步方向。"
              "每个方向要具体可执行，避开已经枯掉的路。只输出 JSON 数组，每项含 direction 和 first_step 两个字段，不要其他文字。\n"
              f"路径：{[x['title']+'/'+x['state'] for x in path]}\n"
              f"当前节点：{title}\n"
              f"同级分叉：{siblings}\n"
              f"已放弃：{dead or '无'}")
    try:
        r = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "messages":[{"role":"user","content":prompt}], "temperature":0.7, "max_tokens":600}, timeout=40)
        if r.status_code == 429: raise HTTPException(429, {"code": "AI_RATE_LIMITED", "msg": "请求太频繁，请稍后再试"})
        if r.status_code >= 500: raise HTTPException(503, {"code": "AI_UNAVAILABLE", "msg": "AI 暂时不可用，请稍后再试"})
        if r.status_code >= 400: raise HTTPException(503, {"code": "AI_UNAVAILABLE", "msg": "AI 暂时不可用，请稍后再试"})
        txt = r.json()["choices"][0]["message"]["content"]
        import re as _re, json as J
        m = _re.search(r"\[.*\]", txt, _re.S); data = J.loads(m.group(0) if m else txt)
        out=[]
        for item in data[:3]:
            if isinstance(item, dict) and item.get("direction") and item.get("first_step"):
                out.append({"direction": str(item["direction"])[:80], "first_step": str(item["first_step"])[:160]})
        out = _filter_suggestions(out)
        if not out: raise HTTPException(503, {"code": "AI_UNAVAILABLE", "msg": "AI 暂时不可用，请稍后再试"})
        return out
    except HTTPException: raise
    except Exception as e:
        print("llm_suggest_fail", e)
        raise HTTPException(503, {"code": "AI_UNAVAILABLE", "msg": "AI 暂时不可用，请稍后再试"})

@app.post("/api/v1/nodes/{nid}/suggest")
def suggest(nid: int, x_user_id: int = Header(...)):
    with Session(engine) as s:
        n = s.get(Node, nid)
        if not n: raise HTTPException(404)
        t = s.get(Tree, n.tree_id)
        if not t or t.owner_id != x_user_id: raise HTTPException(403)
        path, siblings = path_ctx(s, n)
        real = _llm_suggest(path, siblings, n.title)
        return dict(mock=False, generated_by="ai", provider="siliconflow", context=dict(path=path, siblings=siblings), suggestions=real)

@app.get("/api/v1/nodes/{nid}/suggest/example")
def suggest_example(nid: int, x_user_id: int = Header(...)):
    """仅开发调试用的示例候选，前端正式路径不要调。"""
    with Session(engine) as s:
        n = s.get(Node, nid)
        if not n: raise HTTPException(404)
        path, siblings = path_ctx(s, n)
        cands = [dict(direction=f"{n.title}：找一个最小例子", first_step="花 30 分钟照着跑通一个最简单的例子"),
                 dict(direction=f"{n.title}：做一个小作品", first_step="定一个能在一天内做完的小目标，写下验收标准")]
        return dict(mock=True, generated_by="example", context=dict(path=path, siblings=siblings), suggestions=cands)

@app.post("/api/v1/nodes/{nid}/attachments")
async def upload_att(nid: int, kind: str = Form("file"), name: str = Form(""), text: Optional[str] = Form(None), file: Optional[UploadFile] = File(None), x_user_id: int = Header(...)):
    if kind not in {"text", "image", "file", "doc", "pdf", "excel", "code"}: raise HTTPException(400, {"code":"BAD_KIND","msg":"kind 支持 text/image/file/doc/pdf/excel/code"})
    with Session(engine) as s:
        n = s.get(Node, nid)
        if not n or s.get(Tree, n.tree_id).owner_id != x_user_id: raise HTTPException(403)
        storage_key = None
        if file is not None:
            ext = Path(file.filename or "bin").suffix[:20]
            fname = f"{uuid.uuid4().hex}{ext}"
            dest = UPLOAD_DIR / fname
            with dest.open("wb") as f: shutil.copyfileobj(file.file, f)
            storage_key = fname
            name = name or (file.filename or fname)
        elif kind == "text":
            if not text: raise HTTPException(400, "text 附件需要 text 字段")
            name = name or "笔记"
        else:
            raise HTTPException(400, "需要上传文件")
        a = Attachment(node_id=nid, kind=kind, name=name, url=storage_key, text=text); s.add(a); s.flush()
        # url 字段存 storage_key；对外序列化成鉴权地址
        s.commit(); return ser_att(a)


@app.get("/api/v1/nodes/{nid}/attachments")
def list_att(nid: int, q: Optional[str] = None, kind: Optional[str] = None, sort: str = "newest"):
    with Session(engine) as s:
        if not s.get(Node, nid): raise HTTPException(404)
        rows = s.query(Attachment).filter_by(node_id=nid).all()
        if kind: rows = [a for a in rows if a.kind == kind]
        if q:
            ql = q.lower()
            rows = [a for a in rows if ql in (a.name or "").lower() or ql in (a.text or "").lower()]
        if sort == "name": rows.sort(key=lambda a: (a.name or "").lower())
        elif sort == "kind": rows.sort(key=lambda a: (a.kind, a.name or ""))
        elif sort == "oldest": rows.sort(key=lambda a: a.created_at)
        else: rows.sort(key=lambda a: a.created_at, reverse=True)
        return [ser_att(a) for a in rows]

@app.delete("/api/v1/attachments/{aid}")
def del_att(aid: int, x_user_id: int = Header(...)):
    with Session(engine) as s:
        a = s.get(Attachment, aid)
        if not a: raise HTTPException(404)
        n = s.get(Node, a.node_id)
        if s.get(Tree, n.tree_id).owner_id != x_user_id: raise HTTPException(403)
        s.delete(a); s.commit(); return {"ok": True}

class PublishIn(BaseModel):
    show_dead: bool = True
    text_attachments_only: bool = True

@app.post("/api/v1/trees/{tid}/publish")
def publish(tid: int, p: PublishIn = PublishIn(), x_user_id: int = Header(...)):
    with Session(engine) as s:
        t = s.get(Tree, tid)
        if not t or t.owner_id != x_user_id: raise HTTPException(403)
        fruits = [n for n in s.query(Node).filter_by(tree_id=tid) if (getattr(n, "ripeness", None) or "none") == "ripe"]
        if not fruits: raise HTTPException(400, "至少要有一个已摘熟（ripe）的节点才能上架")
        t.is_public = 1; t.show_dead = int(p.show_dead); t.text_attachments_only = int(p.text_attachments_only); s.commit(); return ser_tree(t, s)

@app.post("/api/v1/trees/{tid}/unpublish")
def unpublish(tid: int, x_user_id: int = Header(...)):
    with Session(engine) as s:
        t = s.get(Tree, tid)
        if not t or t.owner_id != x_user_id: raise HTTPException(403)
        t.is_public = 0; s.commit(); return ser_tree(t, s)


from fastapi.responses import FileResponse

@app.get("/api/v1/attachments/{aid}/file")
def get_att_file(aid: int, x_user_id: int = Header(...)):
    with Session(engine) as s:
        a = s.get(Attachment, aid)
        if not a or not a.url: raise HTTPException(404)
        n = s.get(Node, a.node_id); t = s.get(Tree, n.tree_id)
        # 本人，或已上架的公开树（且附件按公开规则可见）
        ok = t.owner_id == x_user_id
        if not ok and t.is_public:
            if t.text_attachments_only and a.kind != "text": ok = False
            else: ok = True
        if not ok: raise HTTPException(403, {"code":"FORBIDDEN","msg":"没有权限查看这个附件"})
        path = UPLOAD_DIR / a.url
        if not path.exists(): raise HTTPException(404)
        return FileResponse(path, filename=a.name)




def public_view(t, s):
    d = ser_tree(t, s)
    nodes = d["nodes"]
    if not t.show_dead:
        dead = {n["id"] for n in nodes if n["state"]=="dead"}
        changed = True
        while changed:
            changed = False
            for n in nodes:
                if n["id"] not in dead and n["parent_id"] in dead: dead.add(n["id"]); changed = True
        nodes = [n for n in nodes if n["id"] not in dead]
    if t.text_attachments_only:
        for n in nodes: n["attachments"] = [a for a in n.get("attachments", []) if a["kind"]=="text"]
    d["nodes"] = nodes
    d["owner_id"] = t.owner_id
    d["fruit_count"] = sum(1 for n in nodes if n.get("ripeness")=="ripe")
    d["show_dead"] = bool(t.show_dead); d["text_attachments_only"] = bool(t.text_attachments_only)
    return d

@app.get("/api/v1/market/{tid}")
def market_detail(tid: int):
    with Session(engine) as s:
        t = s.get(Tree, tid)
        if not t or not t.is_public: raise HTTPException(404)
        return public_view(t, s)

@app.post("/api/v1/market/{tid}/fork")
def fork(tid: int, x_user_id: int = Header(...)):
    """一人一树：无树则建唯一树并挂入；已有树则把对方树（原根）作为新想法枝合并进来。"""
    with Session(engine) as s:
        t = s.get(Tree, tid)
        if not t or not t.is_public: raise HTTPException(404)
        if t.owner_id == x_user_id: raise HTTPException(400, {"code": "OWN_TREE", "msg": "这是你自己的树"})
        mine = ensure_my_tree(s, x_user_id)
        trunk = _trunk(s, mine.id)
        idea = _copy_subtree_as_idea(s, t.id, mine, trunk.id, reset_grow=True)
        if not idea:
            raise HTTPException(400, {"code": "EMPTY_TREE", "msg": "对方树上没有可合并的枝"})
        mine.forked_from = t.id
        mine.forked_title = t.title
        mine.forked_owner_id = t.owner_id
        # 装束并集，不覆盖已有
        dec = list(dict.fromkeys(_decorations(mine) + _decorations(t)))
        mine.decorations = json.dumps(dec, ensure_ascii=False)
        mine.last_grown_at = now()
        s.commit(); return ser_tree(mine, s)


@app.delete("/api/v1/trees/{tid}")
def delete_tree(tid: int, x_user_id: int = Header(...)):
    with Session(engine) as s:
        t = s.get(Tree, tid)
        if not t: raise HTTPException(404)
        if t.owner_id != x_user_id: raise HTTPException(403)
        ids = [n.id for n in s.query(Node).filter_by(tree_id=tid)]
        if ids: s.query(Attachment).filter(Attachment.node_id.in_(ids)).delete(synchronize_session=False)
        s.query(Node).filter_by(tree_id=tid).delete()
        s.query(Tree).filter_by(forked_from=tid).update({Tree.forked_from: None}, synchronize_session=False)
        s.delete(t); s.commit(); return {"ok": True}


import hashlib, hmac, os, secrets, base64, json as _json, time
from fastapi import Request
from fastapi.responses import JSONResponse
def _load_secret():
    if os.environ.get("GUOZI_SECRET"): return os.environ["GUOZI_SECRET"]
    f = Path(__file__).with_name(".secret")
    if not f.exists(): f.write_text(secrets.token_hex(32)); f.chmod(0o600)
    return f.read_text().strip()
SECRET = _load_secret()
AVATARS = ["pinecone", "acorn", "mushroom", "bird", "leaf", "fern"]
def _hash(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200000).hex()
def _check(pw, h): return hmac.compare_digest(_hash(pw, h.split("$")[0]), h)
def make_token(uid):
    body = base64.urlsafe_b64encode(_json.dumps({"uid": uid, "exp": int(time.time())+30*86400}).encode()).decode()
    return body + "." + hmac.new(SECRET.encode(), body.encode(), "sha256").hexdigest()
def read_token(tok):
    try:
        body, sig = tok.split(".")
        if not hmac.compare_digest(sig, hmac.new(SECRET.encode(), body.encode(), "sha256").hexdigest()): return None
        d = _json.loads(base64.urlsafe_b64decode(body)); return d["uid"] if d["exp"] > time.time() else None
    except Exception: return None

@app.middleware("http")
async def bearer_to_uid(request: Request, call_next):
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        uid = read_token(auth[7:])
        if uid is None: return JSONResponse({"detail": {"code": "TOKEN_INVALID", "msg": "登录已过期，请重新登录"}}, 401)
        h = [(k, v) for k, v in request.scope["headers"] if k != b"x-user-id"]
        h.append((b"x-user-id", str(uid).encode())); request.scope["headers"] = h
    elif os.environ.get("GUOZI_DEV_AUTH") != "1":
        request.scope["headers"] = [(k, v) for k, v in request.scope["headers"] if k != b"x-user-id"]
    return await call_next(request)

def _check_nick(n):
    n = (n or "").strip()
    if not (2 <= len(n) <= 12): raise HTTPException(400, {"code": "BAD_NICKNAME", "msg": "昵称要 2 到 12 个字"})
    words = [w.strip().lower() for w in Path(__file__).with_name("banned_words.txt").read_text().splitlines() if w.strip()]
    if any(w in n.lower() for w in words): raise HTTPException(400, {"code": "BAD_NICKNAME", "msg": "昵称里有不能用的词"})
    return n
def _default_nick(p):
    if p.nickname: return _check_nick(p.nickname)
    try: return _check_nick(p.username[:12])
    except HTTPException: return "林间新果农"
def ser_user(u):
    masked = None
    if u.phone: masked = u.phone[:3] + "****" + u.phone[-4:]
    return dict(id=u.id, username=u.username, nickname=u.nickname, avatar=u.avatar, phone_bound=bool(u.phone), phone_masked=masked)


class RegIn(BaseModel):
    username: str; password: str; nickname: Optional[str] = None; avatar: Optional[str] = None
    agreed: bool = False; agreement_version: Optional[str] = None
class LoginIn(BaseModel):
    username: str; password: str

@app.get("/api/v1/auth/avatars")
def avatars(): return AVATARS

@app.post("/api/v1/auth/register")
def register(p: RegIn):
    import re as _re
    if not _re.fullmatch(r"[A-Za-z0-9_]{3,20}", p.username): raise HTTPException(400, {"code": "BAD_USERNAME", "msg": "用户名 3 到 20 位，只能用字母、数字和下划线"})
    if len(p.password) < 6: raise HTTPException(400, {"code": "BAD_PASSWORD", "msg": "密码至少 6 位"})
    if not p.agreed or not p.agreement_version: raise HTTPException(400, {"code": "AGREEMENT_REQUIRED", "msg": "请先阅读并同意用户协议和隐私政策"})
    if p.avatar and p.avatar not in AVATARS: raise HTTPException(400, {"code": "BAD_AVATAR", "msg": "头像不在可选列表里"})
    with Session(engine) as s:
        if s.query(User).filter_by(username=p.username).first(): raise HTTPException(409, {"code": "USERNAME_TAKEN", "msg": "这个用户名已经被用了"})
        u = User(username=p.username, nickname=_default_nick(p), avatar=p.avatar or "pinecone", pw_hash=_hash(p.password), agreed_at=now(), agreement_version=p.agreement_version[:20]); s.add(u); s.commit()
        return dict(token=make_token(u.id), user=ser_user(u))

@app.post("/api/v1/auth/login")
def login(p: LoginIn):
    with Session(engine) as s:
        u = s.query(User).filter_by(username=p.username).first()
        if not u or not _check(p.password, u.pw_hash): raise HTTPException(401, {"code": "BAD_CREDENTIALS", "msg": "用户名或密码不对"})
        return dict(token=make_token(u.id), user=ser_user(u))

@app.get("/api/v1/auth/me")
def me(x_user_id: int = Header(...)):
    with Session(engine) as s:
        u = s.get(User, x_user_id)
        if not u: raise HTTPException(404, {"code": "NO_USER", "msg": "没有这个账号"})
        return ser_user(u)

class MeIn(BaseModel):
    nickname: Optional[str] = None; avatar: Optional[str] = None
@app.patch("/api/v1/auth/me")
def update_me(p: MeIn, x_user_id: int = Header(...)):
    with Session(engine) as s:
        u = s.get(User, x_user_id)
        if not u: raise HTTPException(404)
        if p.avatar:
            if p.avatar not in AVATARS: raise HTTPException(400, {"code": "BAD_AVATAR", "msg": "头像不在可选列表里"})
            u.avatar = p.avatar
        if p.nickname is not None: u.nickname = _check_nick(p.nickname)
        s.commit(); return ser_user(u)


from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
@app.exception_handler(RequestValidationError)
async def _missing_auth(request, exc):
    if any(e.get("loc", [None, None])[:2] == ("header", "x-user-id") for e in exc.errors()):
        return JSONResponse({"detail": {"code": "AUTH_REQUIRED", "msg": "请先登录"}}, 401)
    return await request_validation_exception_handler(request, exc)


# ---- phone bind ----
from collections import defaultdict
_phone_codes = {}  # phone -> {code, exp, uid}
_phone_send_ts = defaultdict(list)  # key -> [ts]

class PhoneSendIn(BaseModel):
    phone: str
    purpose: str = "bind"  # bind | reset
class PhoneVerifyIn(BaseModel):
    phone: str
    code: str
    purpose: str = "bind"

def _ok_phone(phone: str):
    import re
    if not re.fullmatch(r"1\d{10}", phone or ""):
        raise HTTPException(400, {"code": "BAD_PHONE", "msg": "请输入 11 位大陆手机号"})
    return phone

def _rate(key: str, limit: int, window: int):
    nowt = time.time()
    arr = [t for t in _phone_send_ts[key] if nowt - t < window]
    _phone_send_ts[key] = arr
    if len(arr) >= limit:
        raise HTTPException(429, {"code": "SMS_RATE_LIMITED", "msg": "发送太频繁，请稍后再试"})
    arr.append(nowt); _phone_send_ts[key] = arr

def _issue_code(phone: str, uid: int, purpose: str):
    _rate(f"p:{phone}", 3, 600)
    _rate(f"u:{uid}", 5, 600)
    code = f"{secrets.randbelow(1000000):06d}"
    _phone_codes[(phone, purpose)] = {"code": code, "exp": time.time()+300, "uid": uid}
    # 开发期：无短信通道时把验证码写进本地文件，正式环境走私聊配短信
    if os.environ.get("SMS_PROVIDER") != "1":
        Path("uploads").mkdir(exist_ok=True)
        Path("uploads/.last_sms_code").write_text(f"{phone} {purpose} {code}\n")
        print(f"[dev-sms] {phone} {purpose} {code}")
    return code

@app.post("/api/v1/auth/phone/send")
def phone_send(p: PhoneSendIn, x_user_id: int = Header(...)):
    phone = _ok_phone(p.phone)
    if p.purpose not in ("bind", "reset"): raise HTTPException(400, {"code": "BAD_PURPOSE", "msg": "purpose 只能是 bind 或 reset"})
    with Session(engine) as s:
        u = s.get(User, x_user_id)
        if not u: raise HTTPException(404, {"code": "NO_USER", "msg": "请先注册账号"})
        other = s.query(User).filter(User.phone==phone, User.id!=x_user_id).first()
        if other: raise HTTPException(409, {"code": "PHONE_TAKEN", "msg": "这个手机号已经绑定过其他账号"})
        if p.purpose == "bind" and u.phone == phone:
            raise HTTPException(400, {"code": "ALREADY_BOUND", "msg": "已经绑定过这个手机号了"})
        code = _issue_code(phone, x_user_id, p.purpose)
        out = dict(ok=True, expires_in=300, dev=os.environ.get("SMS_PROVIDER")!="1")
        if out["dev"]: out["dev_code"] = code  # 仅开发期，正式短信通道开启后不会返回
        return out

@app.post("/api/v1/auth/phone/bind")
def phone_bind(p: PhoneVerifyIn, x_user_id: int = Header(...)):
    phone = _ok_phone(p.phone)
    if p.purpose != "bind": raise HTTPException(400, {"code": "BAD_PURPOSE", "msg": "绑定请用 purpose=bind"})
    rec = _phone_codes.get((phone, "bind"))
    if not rec or rec["uid"] != x_user_id or time.time() > rec["exp"] or rec["code"] != p.code:
        raise HTTPException(400, {"code": "BAD_CODE", "msg": "验证码不对或已过期"})
    with Session(engine) as s:
        u = s.get(User, x_user_id)
        if not u: raise HTTPException(404)
        other = s.query(User).filter(User.phone==phone, User.id!=x_user_id).first()
        if other: raise HTTPException(409, {"code": "PHONE_TAKEN", "msg": "这个手机号已经绑定过其他账号"})
        u.phone = phone; s.commit(); _phone_codes.pop((phone, "bind"), None)
        return ser_user(u)

@app.post("/api/v1/auth/phone/unbind")
def phone_unbind(x_user_id: int = Header(...)):
    with Session(engine) as s:
        u = s.get(User, x_user_id)
        if not u: raise HTTPException(404)
        if not u.phone: raise HTTPException(400, {"code": "NOT_BOUND", "msg": "还没有绑定手机号"})
        u.phone = None; s.commit(); return ser_user(u)


class CompleteIn(BaseModel):
    note: Optional[str] = None
    link: Optional[str] = None

@app.post("/api/v1/nodes/{nid}/complete")
def complete_node(nid: int, p: Optional[CompleteIn] = None, x_user_id: int = Header(...)):
    """完结=摘熟确认：ripeness→ripe，state→fruit；已是 ripe 则只确认/更新收获 note/link。"""
    p = p or CompleteIn()
    with Session(engine) as s:
        n = s.get(Node, nid)
        if not n: raise HTTPException(404)
        t = s.get(Tree, n.tree_id)
        if not t or t.owner_id != x_user_id: raise HTTPException(403)
        if n.parent_id is None: raise HTTPException(400, {"code": "SEED_NO_FRUIT", "msg": "种子节点不能完结/摘熟"})
        if n.state == "bud" and (getattr(n, "ripeness", None) or "none") == "none":
            raise HTTPException(400, {"code": "NEED_FRUIT", "msg": "还没有挂果，先升到绿叶再摘熟"})
        n.ripeness = "ripe"
        n.state = "fruit"
        if p.note is not None: n.note = p.note
        if p.link is not None: n.link = p.link
        s.commit(); return ser_node(n, s)


@app.delete("/api/v1/nodes/{nid}")
def delete_node(nid: int, x_user_id: int = Header(...)):
    with Session(engine) as s:
        n = s.get(Node, nid)
        if not n: raise HTTPException(404)
        t = s.get(Tree, n.tree_id)
        if not t or t.owner_id != x_user_id: raise HTTPException(403)
        if n.parent_id is None: raise HTTPException(400, {"code": "SEED_PROTECTED", "msg": "种子节点不能删"})
        kids = s.query(Node).filter_by(parent_id=nid).all()
        alive = [k for k in kids if k.state != "dead"]
        if alive:
            raise HTTPException(400, {"code": "CHILDREN_NOT_DEAD", "msg": f"还有 {len(alive)} 根子枝未折断，先把子枝标成枯枝再删"})
        # 枯枝子节点一并删掉
        def wipe(node_id):
            for c in s.query(Node).filter_by(parent_id=node_id).all():
                wipe(c.id)
            s.query(Attachment).filter_by(node_id=node_id).delete()
            s.delete(s.get(Node, node_id))
        wipe(nid); t.last_grown_at = t.last_grown_at; s.commit()
        return {"ok": True}
