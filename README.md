# ETH Whale Extractor

Repo untuk mengekstrak dan menganalisis wallet Ethereum publik yang memiliki saldo **> 25 ETH**.

## Tujuan
- Mengambil data dari sumber database/public dataset yang legal dan dapat diakses publik
- Memfilter wallet dengan saldo ETH > 25
- Menyimpan hasil dalam format yang mudah dipakai ulang (CSV/JSON/Parquet)
- Menyediakan pipeline analisis sederhana dan terdokumentasi

## Prinsip
- Hanya menggunakan data publik / open datasets / RPC yang sah
- Tidak menyimpan secrets di repo
- Fokus pada reproducibility dan auditability

## Struktur Awal
- `src/` - kode extractor dan transformasi data
- `scripts/` - utility/runner
- `data/` - output lokal (di-ignore)
- `docs/` - catatan sumber data, skema, dan asumsi

## Langkah berikutnya
1. Pilih sumber data publik
2. Definisikan skema output
3. Implementasi extractor + filter saldo > 25 ETH
4. Tambahkan validasi dan logging
