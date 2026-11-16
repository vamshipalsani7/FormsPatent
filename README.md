# IPO Form Filler

A small local tool that fills in Indian Patent Office forms from saved client
details. You enter a client's common details once, then download any of the 34
current IPO forms (Form 1 to Form 31, including 7A, 8A and 18A) as an editable
Word document with those details already filled in.

Everything runs on your own computer. Client details are stored only in the
tool's `data` folder and are never uploaded anywhere. The one exception is PIN
code lookup, which sends just the PIN/postcode to a public postcode service.

## Download and run

### Windows: the app (nothing to install)

**[⬇ Download IPO-Form-Filler-Windows.zip](https://github.com/vamshipalsani7/FormsPatent/raw/main/downloads/IPO-Form-Filler-Windows.zip)** (about 20 MB, Windows 10 or 11)

1. Right-click the downloaded zip and choose **Extract All…**. Don't run the app
   from inside the zip.
2. Open the extracted folder and double-click **`IPO Form Filler.exe`**.
3. The tool opens in **its own window**; no web browser is involved. Closing
   the window stops it.
   - **Download buttons** open a normal Windows "Save As" dialog. After saving,
     click the message to open the file in Word.
   - **View official PDF** opens the blank government form in a separate window.

**Works offline.** The only feature that needs internet is the automatic PIN
code look-up (city, state, areas). Without a connection, an Indian PIN still
fills in the State, and the rest can be typed in. The app uses Microsoft Edge
WebView2, which is part of Windows 10 and 11. On the rare PC without it, the
tool opens in your web browser instead.

**Your clients stay on this computer.** They're saved in one fixed place for
your Windows user: `%LOCALAPPDATA%\IPO Form Filler\data`. The Home screen
shows the full path and has an **Open folder** button, useful for backups.

- **Updating:** download the new version and run it. It uses the same clients
  automatically, wherever you keep the `.exe`. There's nothing to copy.
- **Moving from v1.1–1.2.1:** those versions kept a `data` folder next to the
  `.exe`. The first time the new version runs from that folder, it brings those
  clients in once and tells you. The old folder can then be deleted.

> **Windows warnings.** The app isn't code-signed yet, so Windows doesn't
> recognise it.
> - **"Windows protected your PC":** click **More info**, then **Run anyway**.
> - **"Smart App Control blocked an app…"** (Windows 11): there is no way to run
>   unsigned apps. Use the Python version below instead, which Smart App Control
>   allows.

### Any computer: the Python version

**[⬇ Download IPO-Form-Filler.zip](https://github.com/vamshipalsani7/FormsPatent/raw/main/downloads/IPO-Form-Filler.zip)** (about 4 MB, needs Python)

1. **Install Python 3.9 or newer** from <https://www.python.org/downloads/>, if
   you don't have it. On Windows, tick **"Add python.exe to PATH"** during
   installation.
2. **Windows only:** right-click the zip, choose **Properties**, tick
   **Unblock**, click **OK**, then **Extract All…**.
3. **Start the tool:**
   - **Windows:** double-click **`IPO Form Filler.pyw`**. It opens in your
     browser with a small Open / Stop window. To get the app's own window
     instead, first run `py -m pip install pywebview`.
   - **Mac / Linux:** open a terminal in the folder and run `./start.sh`.

| If you see… | Do this |
|---|---|
| **"Windows protected your PC"** | Click **More info**, then **Run anyway**, or unblock the zip first (step 2). |
| The `.pyw` file opens in a text editor, or does nothing | Python isn't installed for all users / file types. Reinstall it from python.org with default options, or use `Start IPO Form Filler.bat`. |
| **Windows Defender Firewall** asks about Python | Either button is fine. The tool only talks to your own computer. |

**From the code:** clone this repository and run `python server.py`.

Starting the tool a second time doesn't start a second copy; it simply opens
the one already running.

## How it works

1. **Home**: choose *Add new client*, or pick an *Existing client* from the
   drop-down or the client list.
2. **Client details**: enter the details that repeat across the forms:
   - client type and applicant category
   - applicants
   - **projects**: as many inventions as the client has. Each project has its
     own title, application number and date, patent number and date, and
     inventors
   - patent agent
   - address for service in India
   - who signs, and which patent office

   No field is required. Some fields help you fill in:
   - **Names** (applicants, inventors, agent, service, signatory) are
     capitalised when you leave the field. "acme innovations pvt ltd" becomes
     "Acme Innovations Pvt Ltd" and "s. mehta" becomes "S. Mehta". Words you
     type with your own capitals (IBM, McKinsey) are left alone.
   - **Every field with a known format is checked** when you leave it. Red
     messages must be fixed (or the field cleared) before saving. Amber ones are
     advice only. The server applies the same rules.

     | Field | Rule |
     |---|---|
     | Application no. | 12 digits: year + office code (11 Delhi, 21 Mumbai, 31 Chennai, 41 Kolkata) + serial, e.g. `202441012345`. The older `1234/DEL/2006` style is also accepted. Amber advice appears if the year differs from the filing date or the office differs from the client's patent office. |
     | Patent no. | Digits only, up to 7 (`IN 512345` becomes `512345`) |
     | IN/PA no. | `IN/PA-1234` (typing `1234` is enough) |
     | Filing / grant date | Not in the future and not before 1970; grant date not before filing date |
     | Title of invention | Amber advice above 15 words; maximum 500 characters |
     | Applicant type | Each applicant is an individual or a company/organisation. Gender and age apply only to individuals, and switching to a company clears them. Inventors are always individuals, and *Same as applicants* skips companies. |
     | Age | Whole number of years, 1–120. Amber advice for an applicant under 18 or anyone over 100. Filled into Form 1. |
     | Gender | One of the listed choices; individuals only |
     | Names of people (individual applicants, inventors, agent, signatory) | Letters, spaces and `. ' -` only; no numbers |
     | Company / service names | Letters, digits, spaces and `. , ' - & ( ) / + :` |
     | City, state, designation | No numbers or stray symbols |
     | E-mail, phone, PIN | See below |
     | Countries, drop-downs | Must be one of the listed choices |
   - **Country fields** (nationality, residence, address) are type-to-search
     lists. Type "In" and pick India; common short forms such as USA, UK and
     UAE also work. Text that isn't in the list is not saved.
   - **Phone fields** have a country-code picker (+91, +1, +44 …) followed by
     the number. Only digits can be typed. Numbers are checked when you
     leave the field:
     - **+91:** 10 digits. Mobiles start with 6–9. Landlines are the STD code
       plus number; a leading 0 is fine.
     - **+1:** 10 digits.
     - **Other codes:** 4–14 digits.
     
     A client can't be saved with an invalid number.
   - **Addresses** (applicants, inventors, patent agent, and address for
     service): choose the country, then enter the PIN / postal code. City,
     state and the list of areas fill in automatically. The patent office is
     also set from the first applicant's state. *Use applicant 1* and *Use
     agent* copy a whole address into the address for service.
   - **PIN / postal codes** are checked against the chosen country's format.
     - **India:** 6 digits, not starting with 0. Only digits can be typed.
     - **About 45 other countries** have their own format, for example US
       90210 or 90210-1234, UK SW1A 1AA, Canada K1A 0B1, and Japan 100-0001.
     - **Any other country:** 2–10 letters or digits.
     
     Codes are tidied for you ("sw1a1aa" becomes "SW1A 1AA"). A client
     can't be saved with an invalid code.
     - For India the lookup uses India Post; for about 60 other countries it
       uses Zippopotam. Only the code and country are sent.
     - Offline, an Indian PIN still fills its state.
   
   Save, and you go back to Home. You can open this page again at any time
   with **Edit details**.
3. **Select a form**: choose the project at the top, then pick from all 34
   forms. Search by number ("18", "7A") or by words ("opposition"). Choose
   *No specific project* for forms that aren't about one invention, such as
   Form 22. Then only the client's own details are filled in.
4. **Form preview**: shows the form with filled-in details highlighted in green
   and blank fields hatched. Click **Download Word (.docx)** to download it, then
   fill in the remaining blanks in Word. **Official blank PDF** opens the
   government form for reference.

What is filled in and what is left blank:

- **Filled in:** client details only.
- **Always left blank:** anything that applies to only one filing, such as
  grounds, reasons, fees, and signing dates.
- **Picked for you:**
  - "I / We" and "my / our" are chosen from the number of applicants. In Word,
    the other choice is shown struck through.
- **Not filled from the client's own details:** on opposition, compulsory
  licence and revocation forms (7, 7A, 14, 17, 19), the patent belongs to
  someone else. On these forms the client is filled in as the opponent or
  applicant.

## Files

| Path | What it is |
|---|---|
| `IPO Form Filler.pyw` | Starts the tool: in its own window (pywebview) when available, otherwise in the browser. The `.exe` is built from it. |
| `server.py` | Local web server and API |
| `ipoforms/prefill.py` | Matches client details to the fields of each form |
| `ipoforms/docx_writer.py` | Writes the Word document |
| `ipoforms/store.py` | Saves clients in `clients.json` in the data folder |
| `forms/definitions/` | Field-by-field definition of each IPO form |
| `forms/official/` | Official blank PDFs |
| `web/` | The interface (HTML/CSS/JS) |
| `tests/` | `python -m unittest discover -s tests` |
| `tools/make_release.py` | Rebuilds `downloads/IPO-Form-Filler.zip`, the Python version: `python tools/make_release.py 1.1.0` |
| `tools/build_exe.py` | Builds `IPO Form Filler.exe` and `downloads/IPO-Form-Filler-Windows.zip` with PyInstaller; see the file for set-up |
| `ipoforms/paths.py` | Where bundled files and client data live, both from source and as the `.exe` |

**Backups:** all client data is in one file, `clients.json`. For the app it's
in `%LOCALAPPDATA%\IPO Form Filler\data`; when run from the code, it's in
`data/`. Copy that file to back up your clients.

- **Automatic backup:** every save also keeps the previous version as
  `data/clients.backup.json`. If `clients.json` is ever damaged, the app says
  so; copy the backup over it to restore.
- **Editing in two tabs:** if a client is changed in another tab or window,
  saving an older copy is refused, so neither set of edits is silently lost.
  Reload the page and make your changes again.
- **Leaving with unsaved edits:** the app asks before leaving the client page.
- **Save as you go:** *Save* (or Ctrl+S) stores the details and keeps you on the
  page. *Save & close* stores them and goes back. The bar at the bottom shows
  "Unsaved changes" or "Saved at …".
- **Drafts:** while you type, unsaved changes are also kept in this browser. If
  the page closes unexpectedly (tab closed, crash, power cut), reopening the
  client offers to *Restore* them.
