# Fixtures — posting contoh agar Person 2/3 bisa tes tanpa crawler (PLAN: 20–50 ASAP).
# Person 1: tambah file mentah ke sini secepatnya, format Post (core/schemas.py).
# File utama: sample_posts.json (12 contoh awal, 4 di antaranya dari PRD).
# instagram_<YYYY-MM-DD>.json — snapshot otomatis respons mentah SocialCrawl per akun ({handle: [items]}).
#   Dibuat collector tiap fetch sukses; dipakai ulang bila API gagal / tanpa key (cadangan demo).
