# Online Auction System using Python (Flask + SQLite)

Mini project for T.Y.B.Sc. Computer Science (Sem V). Implements the design in the project report:
registration/login, create auction listings, browse auctions, place validated bids, bid history,
automatic closed status and winner display.

## Folder structure

```
online_auction/
├── app.py              # Flask routes, validation, database setup
├── requirements.txt
├── test_app.py         # automated tests (python -m unittest)
├── auction.db          # created automatically on first run
├── templates/          # base, index, register, login, new_auction, auction_detail, 404
└── static/style.css
```

## How to run

```bash
python --version                 # Python 3.10+ recommended
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in your browser.

## Demo steps

1. Register two accounts (e.g. `seller1` and `bidder1`; password min. 8 characters).
2. Log in as `seller1` -> **Create Listing** (title, description, starting price, future closing time).
3. Log out, log in as `bidder1`, open the listing, place a bid higher than the current price.
4. Try a lower bid, a non-numeric bid, or a bid on your own listing to see validation messages.
5. After the closing time the auction shows **Closed** and the winner is displayed.

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Auction listings (with `?q=` search) |
| `/register` | GET, POST | Register |
| `/login` | GET, POST | Login |
| `/logout` | GET | Logout |
| `/auction/new` | GET, POST | Create listing |
| `/auction/<id>` | GET | Item details and bid history |
| `/auction/<id>/bid` | POST | Place bid |

## Run the tests

```bash
python -m unittest -v test_app.py
```

## Notes

- Passwords are stored as hashes; all SQL uses parameterised queries.
- Closing times are entered and shown in IST (UTC+05:30) and stored in UTC. Change with the
  `AUCTION_TZ_MINUTES` environment variable.
- Bids are written inside a `BEGIN IMMEDIATE` transaction so two simultaneous bids cannot both
  be accepted against an outdated price.
- A secret key is generated on first run into `.secret_key` (or set `AUCTION_SECRET_KEY`).
- Educational prototype: no payments, CSRF protection, or rate limiting (see Future Scope in the report).
