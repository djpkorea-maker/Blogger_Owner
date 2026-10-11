"""Persistent Dev70 checkpoint for Dev71 changed-only reads; no DB reset on upgrade."""
import json
from .sync import now
VERSION=81

def force_whole_review(version=VERSION,force=False):
    return force or version<71

def remember_checkpoint(store,blog_id,sync,checks):
    from .gates import ENGINE_VERSION
    store.db.execute('CREATE TABLE IF NOT EXISTS application_checkpoints(blog_id TEXT PRIMARY KEY,version INTEGER,recorded_at TEXT,payload TEXT)')
    with store.db:
        store.db.execute('INSERT OR REPLACE INTO application_checkpoints VALUES(?,?,?,?)',(str(blog_id),VERSION,now(),json.dumps({'cache_ready':True,'engine_version':ENGINE_VERSION,'sync':sync,'checks':checks})))

