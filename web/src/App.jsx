import { useEffect, useMemo, useRef, useState } from "react";

const API = "/api";

const VIEWS = [
  { key: "relevant", label: "Relevan" },
  { key: "noise", label: "Tidak relevan" },
  { key: "pending", label: "Menunggu AI" },
  { key: "all", label: "Semua" },
];

function statusOf(post) {
  if (post.is_relevant === true) return "relevant";
  if (post.is_relevant === false) return "noise";
  return "pending";
}

function formatTime(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("id-ID", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

// Hitung kemunculan sebuah field, urut dari yang terbanyak.
function tally(posts, field) {
  const counts = new Map();
  for (const p of posts) {
    if (p[field]) counts.set(p[field], (counts.get(p[field]) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

export default function App() {
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState("relevant");
  const [search, setSearch] = useState("");
  const [location, setLocation] = useState(null);
  const [issue, setIssue] = useState(null);
  const autoSwitched = useRef(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/posts/all?limit=200`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      setPosts(await res.json());
    } catch (e) {
      setError(`Gagal memuat data (${e.message}). Pastikan FastAPI jalan di :8000.`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const stats = useMemo(() => {
    const s = { total: posts.length, relevant: 0, noise: 0, pending: 0 };
    for (const p of posts) s[statusOf(p)] += 1;
    return s;
  }, [posts]);

  const relevantPosts = useMemo(() => posts.filter((p) => statusOf(p) === "relevant"), [posts]);
  const analyzedPosts = useMemo(() => posts.filter((p) => statusOf(p) !== "pending"), [posts]);
  const locations = useMemo(() => tally(analyzedPosts, "location"), [analyzedPosts]);
  const issues = useMemo(() => tally(analyzedPosts, "issue_hint"), [analyzedPosts]);

  // Jangan daratkan user di tab kosong: kalau tidak ada yang relevan,
  // tampilkan Semua agar halaman pertama langsung berisi.
  useEffect(() => {
    if (!loading && !autoSwitched.current && posts.length > 0) {
      autoSwitched.current = true;
      if (relevantPosts.length === 0) setView("all");
    }
  }, [loading, posts, relevantPosts.length]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const ts = (p) => new Date(p.published_at ?? p.collected_at ?? 0).getTime() || 0;
    return posts
      .filter((p) => view === "all" || statusOf(p) === view)
      .filter((p) => !location || p.location === location)
      .filter((p) => !issue || p.issue_hint === issue)
      .filter((p) => !q || `${p.text} ${p.author ?? ""}`.toLowerCase().includes(q))
      .sort((a, b) => ts(b) - ts(a) || (b.relevance_score ?? -1) - (a.relevance_score ?? -1));
  }, [posts, view, search, location, issue]);

  const analyzed = stats.relevant + stats.noise;
  const hasFilter = search || location || issue;

  function clearFilters() {
    setSearch("");
    setLocation(null);
    setIssue(null);
  }

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <h1>Telinga Digital</h1>
          <p>Social listening Malang Raya · review prototype</p>
        </div>
        <button className="btn" onClick={load} disabled={loading}>
          {loading ? "Memuat…" : "Muat ulang"}
        </button>
      </header>

      <section className="funnel" aria-label="Ringkasan pipeline">
        <Stat label="Terkumpul" value={stats.total} hint="posting masuk pipeline" />
        <Stat label="Dianalisis AI" value={analyzed} hint={`${stats.pending} menunggu`} />
        <Stat
          label="Relevan"
          value={stats.relevant}
          hint={analyzed ? `${Math.round((stats.relevant / analyzed) * 100)}% dari yang dianalisis` : "—"}
          tone="good"
        />
        <Stat label="Tidak relevan" value={stats.noise} hint="iklan, promosi, di luar isu publik" />
      </section>

      {error && <div className="alert">{error}</div>}

      <div className="layout">
        <main>
          <div className="toolbar">
            <div className="segmented" role="tablist">
              {VIEWS.map((v) => (
                <button
                  key={v.key}
                  role="tab"
                  aria-selected={view === v.key}
                  className={view === v.key ? "active" : ""}
                  onClick={() => setView(v.key)}
                >
                  {v.label}
                  <span className="count">{v.key === "all" ? stats.total : stats[v.key]}</span>
                </button>
              ))}
            </div>
            <input
              className="search"
              type="search"
              placeholder="Cari teks atau akun…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {hasFilter && (
            <div className="active-filters">
              {location && <Chip onRemove={() => setLocation(null)}>Lokasi: {location}</Chip>}
              {issue && <Chip onRemove={() => setIssue(null)}>Isu: {issue}</Chip>}
              {search && <Chip onRemove={() => setSearch("")}>“{search}”</Chip>}
              <button className="link" onClick={clearFilters}>Hapus filter</button>
            </div>
          )}

          {!loading && !error && visible.length === 0 && (
            <div className="empty">
              {posts.length === 0 ? (
                "Belum ada data. Jalankan pipeline dulu: uv run python -m pipeline.run"
              ) : view === "relevant" ? (
                <>
                  <p>
                    <strong>Belum ada posting relevan.</strong>
                    <br />
                    {stats.pending > 0
                      ? `${stats.pending} posting masih menunggu dinilai AI.`
                      : "AI sudah menilai semua posting, tapi belum ada yang lolos sebagai isu publik — label AI masih tahap awal."}
                  </p>
                  <button className="btn" onClick={() => setView("all")}>
                    Lihat semua {stats.total} posting
                  </button>
                </>
              ) : (
                "Tidak ada posting yang cocok dengan filter ini."
              )}
            </div>
          )}

          <ul className="posts">
            {visible.map((p) => (
              <PostCard key={p.id} post={p} onLocation={setLocation} onIssue={setIssue} />
            ))}
          </ul>
        </main>

        <aside>
          <Breakdown title="Lokasi" rows={locations} selected={location} onSelect={setLocation} />
          <Breakdown title="Isu" rows={issues} selected={issue} onSelect={setIssue} />
          <p className="aside-note">Dihitung dari posting yang sudah dianalisis. Klik untuk memfilter.</p>
        </aside>
      </div>
    </div>
  );
}

function Stat({ label, value, hint, tone }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      <span className="stat-hint">{hint}</span>
    </div>
  );
}

function Chip({ children, onRemove }) {
  return (
    <span className="chip">
      {children}
      <button aria-label="Hapus filter" onClick={onRemove}>×</button>
    </span>
  );
}

function Breakdown({ title, rows, selected, onSelect }) {
  const max = rows[0]?.[1] ?? 1;
  return (
    <section className="panel">
      <h2>{title}</h2>
      {rows.length === 0 && <p className="muted">Belum ada.</p>}
      {rows.slice(0, 8).map(([name, count]) => (
        <button
          key={name}
          className={`bar-row ${selected === name ? "selected" : ""}`}
          onClick={() => onSelect(selected === name ? null : name)}
        >
          <span className="bar-fill" style={{ width: `${(count / max) * 100}%` }} />
          <span className="bar-name">{name}</span>
          <span className="bar-count">{count}</span>
        </button>
      ))}
    </section>
  );
}

function PostCard({ post, onLocation, onIssue }) {
  const status = statusOf(post);
  const time = formatTime(post.published_at ?? post.collected_at);
  const score = post.relevance_score;

  return (
    <li className={`post ${status}`}>
      <div className="post-head">
        <span className={`status ${status}`}>
          {status === "relevant" ? "Relevan" : status === "noise" ? "Tidak relevan" : "Menunggu AI"}
        </span>
        {post.location && (
          <button className="tag" onClick={() => onLocation(post.location)}>{post.location}</button>
        )}
        {post.issue_hint && (
          <button className="tag" onClick={() => onIssue(post.issue_hint)}>{post.issue_hint}</button>
        )}
        {score != null && (
          <span className="score" title="Skor relevansi dari AI">
            <span className="score-track">
              <span className="score-fill" style={{ width: `${score * 100}%` }} />
            </span>
            {score.toFixed(2)}
          </span>
        )}
      </div>

      <p className="post-text">{post.text}</p>
      {post.reason && <p className="post-reason">AI: {post.reason}</p>}

      <div className="post-foot">
        <span>
          {post.platform}
          {post.author ? ` · @${post.author}` : ""}
          {time ? ` · ${time}` : ""}
        </span>
        {post.url ? (
          <a href={post.url} target="_blank" rel="noreferrer">Buka sumber asli ↗</a>
        ) : (
          <span className="muted">Tanpa URL sumber</span>
        )}
      </div>
    </li>
  );
}
