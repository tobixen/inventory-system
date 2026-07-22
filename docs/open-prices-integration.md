Document was AI-generated, with my own comments marked with **User-comment:**.

# Open Prices integration — design notes

*Date: 2026-06-06. Design/research note. **No implementation yet.** Companion to
[`shopping-workflow-redesign-2026-06-06.md`](shopping-workflow-redesign-2026-06-06.md):
this describes hooking Open Food Facts **Open Prices** into the same
post-shopping pipeline, plus using its public price data for "fair price" checks.*

> **Status:** research only. Three distinct features are described and should be
> decided/built independently:
> 1. **Publish prices** — post prices to **Open Prices** during `shop-commit`,
>    alongside the tingbok PUT.
> 2. **Consume prices** — read public prices to get an overview of *typical
>    prices* for a product, domestically and worldwide (post-shop and in-shop).
> 3. **Contribute product photos** — upload photos/data for **unknown products**
>    (EANs that don't resolve in OFF) to the **main OFF product database**. See
>    [Feature 3](#feature-3--contribute-photos-of-unknown-products-main-off-db).
>
> **Owner's build order (2026-06-06):** **Publish prices first** (easy add to the
> existing workflow; receipts will be photographed), **then Consume** ("get
> prices"), then product-photo contribution. First Consume iteration is a plain
> *typical-price overview* — **no FX conversion, no AI "ripped-off" verdicts**;
> show raw prices grouped by currency. The owner accepts that growing the OFF
> dataset over time is the point — it eventually beats tingbok as a source.

---

## What Open Prices is

A separate OFF sub-project from the main product database, with its own DB and
API. The mobile app's "add a price" button talks to this.

- **API base:** `https://prices.openfoodfacts.org/api/v1`
- **Staging (use for all testing):** `https://prices.openfoodfacts.net`
- **Interactive docs / schema:** `…/api/docs`, `…/api/schema`
- **Source:** <https://github.com/openfoodfacts/open-prices> (Django + DRF)
- It is **crowdsourced, public, and attributed to your OFF account.** Treat every
  write as publishing.

### Coverage reality (measured 2026-06-06)

| Probe | Result |
|---|---|
| Total prices in DB | ~263 000 |
| Prices dated 2026 | ~96 700 (project is active & growing fast) |
| Prices at any "Lidl" location, Europe-wide | ~4 100 |
| Prices for Coca-Cola 330 ml (EAN 5449000000996) | **2** |

The headline: the dataset is **active but sparse per-product**. A typical EAN
lookup returns **0–few** rows. This is decisive for the "consume" feature — see
pushback. (It also means our own publishing materially improves the dataset we'd
later consume: a virtuous loop, but a slow one.)

---

## Update 2026-06-06 — first OFF test prep (empirical)

Measured the 2026-06-06 Billa+Lidl EANs against **OFF production**
(`world.openfoodfacts.org/api/v2/product/{ean}`):

| EAN | product | in OFF? |
|---|---|---|
| 20358037 | Бял ориз (Lidl rice) | yes |
| 4056489693307 | ловджийска Луканка | yes |
| 4056489965367 | Chorizo With Chili | yes |
| 3800225663380 | Lentils (red) | yes |
| 3800106408062 | Нут/нахут chickpeas | yes |
| 3800856095703 | Billa rice | **missing** |
| 3800225663700 | Krina chickpeas | **missing** |
| 3800050405919 | Oberon tomatoes | **missing** |
| 3800201253550 | Domenico **dishwasher detergent** | **n/a — not food** (Open Products Facts, not OFF) |

**Build-order question resolved (does product-creation block price-publishing?):**
**No.** Open Prices accepts a price for any `product_code`; it creates a stub
Product from the code and enriches from OFF asynchronously — a price is not
blocked by a missing OFF product. But a price on a bare barcode is low value, so
for the *missing* items it's better to create the OFF product first. Conclusion:
**per-product interleaving**, not a global reorder — product-photo contribution
(Feature 3) moves up from "last" to *alongside* price publishing, but prices for
already-known EANs (5/9 here) proceed independently. Owner's instinct (create
missing products first) is correct for the missing subset.

**Location via photo GPS — confirmed works.** The *in-store* Billa receipt photo
carries Billa's coordinates (≈43.2199, 27.8829); the re-shot receipt photo was
taken at the boat (different coords) — prefer the in-store shot for
reverse-geocoding. EXIF GPS → Nominatim reverse-geocode → cached `shop → OSM`
table. Lidl by photo GPS or address/OSM.

**Detergent caveat:** `3800201253550` is a cleaning product — **out of scope for
OFF** (food only). Belongs to Open Products Facts if anywhere. Its price could
still go to Open Prices (accepts non-food GTINs) but set aside for now.

**SDK available:** `openfoodfacts` 3.3.0 is installed (use it, don't hand-roll the
write API). Staging targets: OFF `world.openfoodfacts.net` (HTTP basic `off:off`
+ an account for writes), Open Prices `prices.openfoodfacts.net` (reachable, 200).

---

## Authentication

### How auth works

`POST /api/v1/auth` (form-encoded) with **either**:
- `username` + `password` (OFF account), **or**
- `access_token` (a Keycloak SSO access token, clear text).

Returns `{"access_token": "<token>", "token_type": "bearer"}`. The token is an
**opaque, DB-backed session token** of the form `<user_id>__U<uuid>` — *not* a
JWT, and with **no intrinsic expiry** (it lives until the session row is deleted,
e.g. by `DELETE /api/v1/session`). Authenticate subsequent calls with **either**:
- `Authorization: Bearer <token>`, **or**
- `Cookie: session=<token>`.

### "Can I extract something from the browser?" — yes

I checked the server source (`open_prices/api/auth/views.py`). When you log in on
the website, the token is stored in a cookie literally named **`session`**, and
the code **deliberately does not set `HttpOnly`** ("still in beta" comment). So:

- **DevTools → Application → Cookies → `session`** gives you the token, or
- the browser console `document.cookie` shows it (because it's not HttpOnly).

**User-comment:** Use rather the python library browser-cookie3 to fetch the cookies from the browser.

> **Response (accepted):** `browser-cookie3` reads the `session` cookie straight
> from the browser's cookie store for the `prices.openfoodfacts.org` domain — no
> manual DevTools copy, no password in the script. Because the cookie is **not
> HttpOnly** it's readable this way. Sketch:
> ```python
> import browser_cookie3
> cj = browser_cookie3.chromium(domain_name="prices.openfoodfacts.org")
> token = next(c.value for c in cj if c.name == "session")
> # use as: Authorization: Bearer <token>   (or just pass the cookiejar to requests)
> ```
> Caveat unchanged: this token's life is tied to the browser session (logout
> kills it). Fine for interactive/manual runs; for an unattended job prefer a
> dedicated `POST /auth` token (below). Also note `browser-cookie3` needs read
> access to the browser profile and may hit the OS keyring on some setups.

That cookie value **is** a valid bearer token — paste it straight into
`Authorization: Bearer …`. No password needed in any script.

**Caveat (why I'd still not rely on the browser cookie long-term):** it shares
its lifetime with the browser session — logging out in the browser
(`DELETE /session`) can invalidate it. A clean script wants an *independent*
token. Each `POST /auth` mints a **new** session, so:

- **Recommended:** do one `POST /api/v1/auth` from a small bootstrap (password
  typed interactively, **never** committed), capture the returned token, store
  **only the token** as a secret. It won't expire on its own and is decoupled
  from browser logouts.
- The browser-cookie trick is a fine **bootstrap shortcut** to get going without
  wiring up the password flow.

### Where to store the token

Per the project's convention question: match whatever `inventory-md` already uses
for secrets. Today this repo has no committed-secrets pattern visible; the safe
default is an env var (`OPENPRICES_TOKEN`) sourced from a gitignored file or the
systemd unit's `EnvironmentFile`. `.gitignore` already excludes the usual
suspects — verify before adding. Decision deferred.

**User-comment:** probably follow the XDG standard and put it under `~/.config/inventory-md` ?

---

## Feature 1 — Publish prices during `shop-commit`

### The hard constraint: every price needs a *proof*

**User-comment:** This is not a big problem, as I already photograph shop receips.  I do see the privacy concern, but personally I don't mind the full shopping information being sent to off.  For Lidl and Decathlon (not much food relevant though) it's a bit extra since I usually download this as json, but not much extra hassle to photograph the receipts.

You **cannot** POST a price without a `proof_id`. A proof is an uploaded
**image** (receipt or price tag). Flow:

```
POST /api/v1/proofs/upload   (multipart: file + type)         -> proof.id
POST /api/v1/prices          (json/form, proof_id + fields)   -> one per line-item
```

- `proof.type` ∈ `PRICE_TAG | RECEIPT | GDPR_REQUEST | SHOP_IMPORT`.
- **One `RECEIPT` proof backs many price rows** — perfect fit for our
  receipt-driven `purchases.jsonl`: upload the receipt photo once, reference its
  `proof_id` on every line-item price.
- A receipt proof can carry `receipt_price_count` / `receipt_price_total` so the
  server can sanity-check that the prices you post sum to the receipt total — a
  free validation gate that mirrors our pipeline philosophy.

This dovetails with the pipeline's existing **photo classification** step
(`label / barcode-only / expiry-only`): a *receipt* photo is just another class,
and it's the proof artifact here.

### Field mapping: ledger row → `PriceCreate`

`purchases.jsonl` already holds nearly everything Open Prices wants.

| Open Prices field | Required | Source in our data | Notes |
|---|---|---|---|
| `proof_id` | **yes** | uploaded receipt photo | one per receipt, reused |
| `product_code` | per PRODUCT | `ean` | GTIN/EAN |
| `price` | yes (effectively) | `unit_price` | **net per-unit** — the ledger books the net paid price (`price_net` on a discounted staging line) |
| `currency` | yes | `currency` | ISO 4217; enum-validated |
| `date` | yes | `date` | receipt date |
| `price_per` | — | derive from `price:.../UNIT` | `UNIT` or `KILOGRAM` only |
| `type` | yes | constant | `PRODUCT` (has EAN) / `CATEGORY` (produce) |
| `category_tag` | per CATEGORY | `category` | for barcodeless produce |
| `location_osm_id`+`location_osm_type` *or* `location_id` | yes | **shop → OSM map (TODO)** | see below |
| `price_is_discounted`, `price_without_discount`, `discount_type` | — | staging `line_total_gross` + `discounts[].openprices_type`, passed via `--discount EAN=GROSS[:TYPE]` | `discount_type` ∈ QUANTITY/SALE/SEASONAL/LOYALTY_PROGRAM/EXPIRES_SOON/PICK_IT_YOURSELF/SECOND_HAND/OTHER. A discounted staging line surfaces the pre-discount per-unit price (`line_total_gross / qty`) and the mapped `openprices_type` (Lidl Plus coupon → LOYALTY_PROGRAM, in-store markdown → EXPIRES_SOON) — build the `--discount` flag from those |
| `product_name` | — | `name` | optional |

**Loose ends to decide:**

- **Locations need OSM identity.** Open Prices keys location off OpenStreetMap
  nodes (`location_osm_id` + `location_osm_type`) or a pre-created `location_id`.
  We shop at a small fixed set ("Lidl Varna", boat marinas, etc.) → build a
  **one-time `shop → OSM` lookup table** once and reuse. `location__osm_name__contains`
  helps find candidates. This is the main new data we don't already have.
  **User-comment:** We have GPS-tracking on the phone, and GPS-coordinates embedded in the photos, could this be used for finding the OSM-identity of unknown shops?
  > **Response (good idea):** yes. Read the photo's EXIF GPS (lat/lon), then
  > reverse-geocode to an OSM object. Best fit here is **OSM's Nominatim
  > reverse-geocode** (`https://nominatim.openstreetmap.org/reverse?lat=..&lon=..`),
  > which returns the `osm_type` + `osm_id` Open Prices wants — or an Overpass
  > "nearest shop node" query for higher precision. Caveats: Nominatim has a
  > strict usage policy (≤1 req/s, User-Agent required) so **cache results**;
  > GPS may resolve to the building/street rather than the exact shop node, so
  > keep a human-confirmed `shop → OSM` table (under `~/.config` or `~/.cache`
  > per the owner's note) and only auto-suggest. Open Prices may also let you
  > create a location from coordinates directly — check before building Overpass
  > logic.
- **Barcodeless produce** (loose veg, fish counter) → `type=CATEGORY` +
  `category_tag` + `price_per=KILOGRAM`. We have `category`; needs mapping to OFF
  category tags (we already do EAN→category via tingbok, so partly solved).
- **Lidl digital receipts have no photo.** `get_data.py` pulls Lidl/Decathlon
  receipts as structured data — there's no receipt *image* to use as proof.
  Options: (a) screenshot/PDF the digital receipt as the proof image, (b) use the
  `SHOP_IMPORT` proof type if it permits non-photo provenance, (c) only publish
  prices for shops where we photograph the paper receipt. **Open question — must
  resolve before publish is viable for Lidl.** **User-comment:** I can start by taking photos of the receipt.

### Where it slots in

Into **`shop-commit` (stage 4)** of the pipeline, as an *additional, opt-in
publish target* next to the tingbok PUT — i.e. **after** the validation gate, on
reviewed rows only, with a **dry-run diff** first. Unlike tingbok, Open Prices
writes are reversible (`DELETE /api/v1/prices/{id}`, you own your rows) — but
they're *public* the moment they land, so gate them like an irreversible step.

---

## Feature 2 — Consume prices ("was I ripped off?" / "good price?")

### Read API (no auth needed; reads are public)

`GET /api/v1/prices` with rich filters, notably:
`product_code`, `product_code__in[]`, `price__gte/__lte`, `currency`,
`date__gte/__year`, `location__osm_name__contains`,
`product__categories_tags__contains`, `order_by` (e.g. `-date`).

### Post-shop fairness check

For each EAN in a `purchases.jsonl` receipt: `GET /prices?product_code=EAN`,
build a price distribution (min / median / max), normalize, and flag rows where
our `unit_price` sits well above the public median.

### In-shop decision support

Given a shopping-list EAN, surface "typical price elsewhere" before buying; and
the cross-country angle the owner cares about — *compare the same `product_code`
across countries/currencies to decide where to stock up* (e.g. Bulgaria vs
Greece before crossing the border).  **User-comment:** it's noe only comparition of the prices for the same EAN, but also prices for the same product that is interessting.

### Why this is harder than it looks — required normalization

**User-comment:** I don't need algorithmical or AI-driven algorithms to decide if I was "ripped off" or not - all I want is to be able to have an overview of what prices are typical, both domestically and other places in the world.

> **Scope (decided):** the first iteration is a **plain overview**, not a verdict
> engine. Fetch the rows, show them grouped **by currency** with date and
> location, and let the human eyeball it. **No FX conversion in iteration 1** —
> just present each currency's prices side by side. The normalization items below
> are **deferred to a later iteration** (and even then, presentation aids, not
> automated judgments):
>
> - **Currency conversion** (EUR/BGN/NOK/…) — *later*; iteration 1 groups by
>   currency instead.
> - **Pack-size / `price_per`** — show `price_per` (UNIT/KILOGRAM) alongside the
>   price so €/kg vs €/unit rows aren't silently mixed. Cheap, worth doing early.
> - **Temporal spread** — show the `date`; optionally filter `date__gte`. No
>   inflation modelling.
> - **Discount flag** — show `price_is_discounted` so sale rows are visible as
>   such. No correction maths.

**User-comment (same-product, not just same EAN):** comparison of prices for the
*same product* (not only the identical EAN) is also interesting.

> **Response:** doable, with limits. The same product often has several EANs
> (regional barcodes, repackagings). Two avenues: (a) query by
> `product__categories_tags__contains` / `product_name` to widen beyond one EAN,
> and (b) lean on OFF's own product grouping where it exists. Iteration 1 stays
> EAN-keyed (simple, exact); "same product across EANs" is a **later** widening
> once the basic overview works. Worth a flag in the output that results are
> EAN-exact and may miss sibling barcodes.

### The bigger realism problem

With Coca-Cola at **2** data points, most EAN lookups will return **nothing or
too little to be statistically meaningful**. As a standalone "am I being ripped
off" oracle, Open Prices is **not there yet** for most of our basket. It's better
framed as: a *bonus* signal when data happens to exist, plus a dataset we help
grow by publishing.

---

## Feature 3 — Contribute photos of unknown products (main OFF DB)

This targets the **main Open Food Facts product database**, *not* Open Prices —
two different systems with two different APIs. It directly closes a loop we
already have: the pipeline says *"if the EAN doesn't resolve, photograph the
product"*. Today those photos just sit locally. Posting them to OFF makes the
EAN resolvable **for everyone — including our own future tingbok/OFF lookups**.

### Why this pairs naturally with prices

When you POST a price for an EAN that OFF has never seen, OFF auto-creates a
**stub product** (we observed real price rows where `product_name` is `null` and
all product fields are empty). Feature 3 is what turns those stubs — and any
unknown EAN we hit — into real products with a photo. So Features 1 and 3 share
the same trigger (an EAN we just bought) and the same raw material (a photo we
already took).

### Endpoints (legacy CGI, still current; auth = OFF account)

Auth is the **same OFF account** as Open Prices, but the main server uses the
**username + password as form fields** on each request (it's migrating to
Keycloak/OAuth bearer tokens, but user_id/password stays supported). Use the
**username, not the email**.

**Upload an image:**
```
POST https://world.openfoodfacts.org/cgi/product_image_upload.pl
  -F user_id=<user>  -F password=<pass>
  -F code=<EAN>
  -F imagefield=front           # or: ingredients / nutrition / packaging / other
                                #     add a lang suffix, e.g. front_en, ingredients_bg
  -F imgupload_front=@/path/to/photo.jpg
```
- Uploading the first image **creates the product** if the `code` is new.
- You can upload several images (front / ingredients / nutrition / packaging).
- The server + Robotoff (OFF's ML) then OCR and auto-extract data from them.

**Set product text fields (optional, same call style):**
```
POST https://world.openfoodfacts.org/cgi/product_jqm2.pl
  -F user_id=<user>  -F password=<pass>
  -F code=<EAN>
  -F product_name=<name>  -F quantity=<e.g. 1 l>  -F brands=<...>  -F categories=<...>
```
There is also a newer JSON write API (`PATCH /api/v3/product/{barcode}`) — check
current OFF docs if we prefer JSON over the CGI form; the CGI endpoints above are
the documented, stable path today.

> **Staging:** `https://world.openfoodfacts.net` (note `.net`). The staging host
> is behind HTTP Basic auth (`off` / `off`) *in addition to* the form
> credentials, to keep it out of search indexes. **Do all first tests there.**

### What we'd send, and from where

The pipeline already classifies photos as `label / barcode-only / expiry-only`.
A **label** photo of an unknown-EAN product is exactly a `front` (and sometimes
`ingredients` / `nutrition`) image. So Feature 3 = "for rows where the EAN didn't
resolve and we have a label photo, upload it to OFF as `front` (+ others if
legible), optionally set `product_name`/`quantity`/`brands` from what we already
typed into the inventory line."

### Caveats specific to product photos (all public, no privacy toggle)

- **Everything here is irrevocably public and CC-licensed.** Unlike receipts,
  product photos have **no `owner_consumption` equivalent** — that's fine (it's a
  product label, not personal data), but make sure no background/personal items
  are in frame. A clean label crop only.
- **Quality bar.** OFF wants in-focus, deduplicated, correctly-oriented photos
  with the right `imagefield`. Junk uploads create moderation work. Gate on the
  same photo-classification confidence the pipeline already computes.
- **Don't double-create.** Before uploading, `GET /api/v2/product/<EAN>.json` (or
  v3) to check the product/photos don't already exist — avoid redundant images.
- **Language suffix matters** for `ingredients`/`packaging` (`_bg`, `_en`, …).
- Belongs in **`shop-commit`**, opt-in, after review, alongside Features 1–2.

---

## Honest pushback

1. **The fairness signal we already own is better.** `purchases.jsonl` + git
   history is **dense for our actual basket**: we can compare our *own* price for
   an EAN over time and across the shops we use — far more relevant than 0–2
   public rows from strangers in other countries. **Build self-comparison first**
   (free, no API, uses existing data); treat Open Prices as augmentation. This is
   the highest-value, lowest-cost piece and it's hiding in plain sight.  **User-comment:** when I start pushing price information to off, it eventually over time will become a richer source than tingbok.
2. **Publishing receipts is a privacy leak.** A `RECEIPT` proof is the *whole
   receipt image*, public, tied to your OFF identity — it can expose loyalty-card
   numbers, card last-4, exact timestamps and locations of your movements. At
   minimum: prefer `PRICE_TAG` proofs, or redact receipts, or don't publish
   receipt images at all and reconsider whether publishing is worth it. Don't
   auto-publish by default. **User-comment:** Are those photos available for anyone to download, or only for select volunteers/AI validating data?  It's generally a real concern, but personally I think I can live with this exposure.
   > **Response (from the source, with one caveat):** Open Prices distinguishes
   > two kinds of proof. `PRICE_TAG` / `SHOP_IMPORT` are **COMMUNITY** (public).
   > `RECEIPT` / `GDPR_REQUEST` are **CONSUMPTION**, and an uploaded proof carries
   > an **`owner_consumption` boolean**: when set, the proof is **excluded from
   > community/public listings** (`ProofQuerySet` filters `owner_consumption=True`
   > out of the community view) — i.e. a receipt can be kept private to your
   > account while the *prices* derived from it are still public. **So: prices are
   > always public; the receipt *image* can be kept non-public by setting
   > `owner_consumption=True` on upload.** Caveat I could **not** fully confirm
   > from source: whether the raw image file URL is hard access-controlled vs.
   > merely unlisted (image files are served from an images dir). **Action:** test
   > on staging — upload a receipt with `owner_consumption=True`, then try to fetch
   > its image URL while logged out. Given the owner is comfortable with the
   > exposure this isn't blocking, but `PRICE_TAG` proofs sidestep it entirely.
3. **Coverage undercuts the in-shop use case today.** Offline-in-shop is the
   stated want, but the public data is both sparse and online-only; you'd be
   pre-fetching a thin snapshot. Manage expectations.
4. **Comparison without FX/size/time normalization is worse than nothing** — it
   produces confident-but-wrong "ripped off" verdicts. If we build consume, the
   normalization layer is the actual work, not the API calls.  **User-comment:** I believe this data will be better for me than no data at all.
5. **Effort vs payoff.** Publish adds an OSM-location mapping, a proof-image
   story (unsolved for Lidl digital receipts), and privacy handling — real work
   for data that mostly benefits the commons, not us. Legitimate as
   contribution; just be honest it's altruism, not self-interest.  **User-comment:** I want this project to succeed.

---

## Open questions / decisions needed

**User-comment:** I think most of the questions below are already answered.  Build the "get prices" on off first.  Publish receipts, that's an easy addition to the workflow I'm already going through.  I'll photograph the Lidl receipts.  shop -> OSM location ... probably under `~/.config` or `~/.cache`

- [x] **Publish at all, given receipt privacy?** Yes — owner accepts exposure.
      Optionally set `owner_consumption=True` to keep receipt *images* unlisted
      (prices stay public); `PRICE_TAG` proofs avoid the issue entirely.
- [x] **Lidl digital receipts (no photo)?** Owner will photograph the paper
      receipt — no special-casing needed.
- [x] **Token / config location?** Under `~/.config/inventory-md` (XDG); shop→OSM
      cache under `~/.config` or `~/.cache`.
- [x] **Build order?** Publish → Consume (no FX) → product photos.
- [ ] **Confirm receipt-image access control** on staging (unlisted vs. truly
      private file URL) — see Feature 1 privacy response.
- [ ] **shop → OSM** resolution: GPS-EXIF + Nominatim reverse-geocode, cached,
      human-confirmed (see locations response). Build when first needed.
- [ ] *Later:* FX source + caching; "same product across EANs" widening.

## Suggested build order (owner-confirmed 2026-06-06)

1. **Publish prices** (opt-in) in `shop-commit`: shop→OSM map → proof upload
   (receipt photo) → `PriceCreate` per line → dry-run diff → behind the
   validation gate. Test against `prices.openfoodfacts.net` (staging) first.
2. **Consume prices** — read-only Open Prices lookup: EAN → list of public
   prices, **grouped by currency, no FX conversion**, showing `price_per`, date,
   location and discount flag. A plain typical-price overview, not a verdict.
3. **Contribute product photos** (Feature 3): for unresolved EANs with a label
   photo, upload to the main OFF DB (`world.openfoodfacts.net` staging first).
4. *Later:* FX-normalized / cross-currency comparison; "same product across
   EANs" widening; GPS→OSM auto-suggest for new shops.

## References

- Open Prices API docs: <https://prices.openfoodfacts.org/api/docs>
- Open Prices source (auth/cookie + proof privacy verified here):
  <https://github.com/openfoodfacts/open-prices>
- OFF "product prices" tutorial:
  <https://openfoodfacts.github.io/openfoodfacts-server/api/tutorials/product-prices/>
- OFF image-upload tutorial (Feature 3):
  <https://openfoodfacts.github.io/openfoodfacts-server/api/tutorial-uploading-photo-to-a-product/>
- OFF write-API tutorial (`product_jqm2.pl` / fields):
  <https://openfoodfacts.github.io/openfoodfacts-server/api/tutorial-off-api/>
