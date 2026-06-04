# MeuDocMed

A patient-centered web platform for storing, organizing, and sharing personal medical documents. Functional academic prototype deployed in production.

**Live demo:** [meudocmed.onrender.com](https://meudocmed.onrender.com)

---

## About

MeuDocMed addresses a structural problem in the Brazilian healthcare system: clinical records scattered across labs, clinics, and hospitals, with no real portability for the patient. The platform centralizes these documents and gives the patient full control over who accesses their information, under what conditions, and for how long.

The project includes two separate portals — one for patients and one for healthcare professionals — along with a Chrome extension for capturing documents directly from health portals such as Resulta/Dasa, Einstein Online, and SMS-Rio systems.

---

## Features

### Patient
- Document upload in 9 clinical categories (lab exam, imaging, report, prescription, medical report, vaccine, hospitalization, surgery, other)
- File validation by extension and by magic number (internal byte content)
- Listing with category filter, name search, and pagination
- Medication management with dosage, frequency, and route of administration
- Granular access control: approve professional requests with configurable time window (10/30/60/120 min) and download permission
- Revoke access at any time
- Temporary sharing links for non-registered recipients
- Real-time notifications via SSE when a professional requests access
- Full access history exportable as PDF
- Account deletion with complete data and file removal

### Healthcare Professional
- Automatic registration verification via federal council APIs (CFM, COFEN, CFO, COFFITO, CFF)
- Patient search by name, CPF, or SUS card number
- Access request with message to patient
- Secure document viewer (download blocked when not permitted)
- Document upload to patient record while access is active

### Distributed Storage
- **Default mode:** Cloudinary (raw file storage)
- **Shamir mode:** when B2 and IDrive are configured, files are encrypted with AES-256-GCM (key derived via PBKDF2-HMAC-SHA256, 100,000 iterations) and the encryption key is split into 3 shares using a custom Shamir's Secret Sharing (2-of-3) scheme implemented from scratch in GF(2^8). Share 1 + encrypted file go to Backblaze B2, share 2 to IDrive e2, share 3 to Cloudinary. Any 2 of the 3 shares reconstruct the key. Failed uploads are automatically retried on next login.

### Authentication
- CPF + password with in-memory rate limiting (5 attempts / 5 min → 10 min lockout)
- Gov.br OAuth 2.0 / OpenID Connect (Brazilian federal identity)
- Google OAuth 2.0
- API token for Chrome extension

### Chrome Extension
- Detects documents on health portals (Resulta/Dasa, Einstein, SMS-Rio, e-SUS) and any PDF open in Chrome
- Sends directly to MeuDocMed without manual download
- Authenticated via token generated in patient profile

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, Flask 3.0, SQLAlchemy 2.0 |
| Database | PostgreSQL (production), SQLite (development) |
| Web server | Gunicorn |
| Storage | Cloudinary, Backblaze B2, IDrive e2 |
| Cryptography | AES-256-GCM, PBKDF2-HMAC-SHA256, Shamir SSS in GF(2^8) |
| External auth | Gov.br OAuth 2.0, Google OAuth 2.0 |
| PDF | PyMuPDF, fpdf2 |
| Email | Flask-Mail |
| Hosting | Render |
| Extension | Chrome Manifest V3 |
| Front-end | HTML/CSS/JS (no framework), PWA with service worker |

---

## Local Setup

```bash
# 1. Clone and create virtual environment
git clone https://github.com/your-username/meudocmed.git
cd meudocmed
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables
cp .env.example .env
# Edit .env with your credentials

# 4. Run
python app.py
```

Access: **http://localhost:5000**

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Flask session key |
| `DATABASE_URL` | No | PostgreSQL URL (defaults to local SQLite) |
| `CLOUDINARY_CLOUD_NAME` | No | Enables Cloudinary storage |
| `CLOUDINARY_API_KEY` | No | |
| `CLOUDINARY_API_SECRET` | No | |
| `B2_ENDPOINT_URL` | No | Enables Shamir SSS (requires B2 + IDrive) |
| `B2_ACCESS_KEY_ID` | No | |
| `B2_SECRET_ACCESS_KEY` | No | |
| `B2_BUCKET` | No | |
| `IDRIVE_ENDPOINT_URL` | No | |
| `IDRIVE_ACCESS_KEY_ID` | No | |
| `IDRIVE_SECRET_ACCESS_KEY` | No | |
| `IDRIVE_BUCKET` | No | |
| `GOOGLE_CLIENT_ID` | No | Enables Google login |
| `GOOGLE_CLIENT_SECRET` | No | |
| `GOOGLE_REDIRECT_URI` | No | |
| `GOVBR_CLIENT_ID` | No | Enables Gov.br login |
| `GOVBR_CLIENT_SECRET` | No | |
| `GOVBR_REDIRECT_URI` | No | |
| `MAIL_SERVER` | No | Enables email (password reset) |
| `MAIL_USERNAME` | No | |
| `MAIL_PASSWORD` | No | |

---

## Chrome Extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `chrome-extension/` folder
5. In MeuDocMed, go to **Profile** and generate an access token
6. Paste the token into the extension

---

## Project Structure

```
meudocmed/
├── app.py                    # Flask application factory
├── config.py                 # Environment-based configuration
├── models.py                 # SQLAlchemy models
├── storage_shamir.py         # Shamir SSS + AES-256-GCM
├── requirements.txt
├── Procfile
├── render.yaml
├── routes/
│   ├── auth.py               # Authentication (CPF, Gov.br, Google)
│   ├── patient.py            # Patient area + extension API
│   ├── professional.py       # Professional portal
│   └── share.py              # Public share links
├── utils/
│   ├── file_utils.py         # Extension and magic number validation
│   ├── storage.py            # Cloudinary / local abstraction
│   ├── validators.py         # CPF, professional registration, council APIs
│   ├── pdf_utils.py          # Access history PDF export
│   └── notifications.py      # SSE real-time notifications
├── templates/                # Jinja2 templates
├── static/                   # CSS, JS, icons, manifest.json, sw.js
└── chrome-extension/         # Chrome Extension (Manifest V3)
    ├── manifest.json
    ├── background.js
    ├── content.js
    ├── popup.html
    └── popup.js
```

---

## Limitations

This is an academic prototype. Notable limitations:

- Patients must upload documents manually — no integration with existing EHR systems
- No full MIME type validation of uploaded files
- No multi-factor authentication
- Shamir storage requires three external services to be simultaneously available
- No user research or usability study validating the design assumptions

---

## License

Developed for academic purposes. Not a replacement for official electronic health records.
