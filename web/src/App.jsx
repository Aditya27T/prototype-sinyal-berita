import { useEffect, useState } from "react";

const API = "/api";

export default function App() {
  const [posts, setPosts] = useState([]);
  const [location, setLocation] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load(loc = "") {
    setLoading(true);
    setError("");
    try {
      const q = loc ? `?location=${encodeURIComponent(loc)}&limit=50` : "?limit=50";
      const res = await fetch(`${API}/posts/relevant${q}`);
      if (!res.ok) throw new Error(`API ${res.status}`);
      setPosts(await res.json());
    } catch (e) {
      setError(`Gagal memuat (${e.message}). Pastikan FastAPI jalan di :8000.`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <>
      <header>
        <h1 style={{ margin: 0 }}>Telinga Digital — Relevant Posts Malang Raya</h1>
        <p style={{ margin: "4px 0 0", opacity: 0.8 }}>Review UI prototype (Person 3) — Bun + React</p>
      </header>
      <main>
        <div className="controls">
          <input
            placeholder="Filter lokasi, mis. Sawojajar"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
          />
          <button onClick={() => load(location)}>Cari</button>
          <button onClick={() => { setLocation(""); load(""); }}>Reset</button>
        </div>
        {loading && <p>Memuat…</p>}
        {error && <p style={{ color: "red" }}>{error}</p>}
        {!loading && !error && posts.length === 0 && <p>Belum ada relevant posts. Jalankan pipeline dulu.</p>}
        {posts.map((p) => (
          <div className="card" key={p.id}>
            <div>{p.text}</div>
            <div className="meta">
              <span className="badge">{p.location ?? "tanpa lokasi"} · {p.issue_hint ?? "tanpa isu"}</span>
              <span>skor {Number(p.relevance_score).toFixed(2)}</span>
              <span>{p.platform}{p.author ? ` · @${p.author}` : ""}</span>
              {p.url && <a href={p.url} target="_blank" rel="noreferrer">buka sumber asli ↗</a>}
            </div>
            {p.reason && <div className="meta">alasan: {p.reason}</div>}
          </div>
        ))}
      </main>
    </>
  );
}
