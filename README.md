# Budget Tracker

A personal budget tracker for PEN (soles) and USD, with separate users. Everything is saved
locally in the `data/` folder:

```
data/users.json                  the list of users (name, type, icon) and who was used last
data/users/<id>/expenses.json    that user's expenses, income, budgets, recurring, categories…
data/users/<id>/receipts/        that user's receipts
data/users/<id>/backups/         that user's automatic daily backups (last 30 kept)
data/users/_deleted/             data of deleted users (moved here, never erased)
```

On the first run, an existing `data/expenses.json` (from before users existed) is moved into
the **Default User**, with a safety copy in its backups. The app name is set in
`expense_tracker/__init__.py` (`APP_NAME`).

## Users

The window opens on a start screen: pick a user card, or "New user" (name, type such as
Personal/Work/Family, and an icon & color). The "⋯" on a card edits or deletes that user.
Inside, the header shows who's active and a "Switch user" button (also in the File menu).

## Setup

Python 3.10+ is required. [Pillow](https://pypi.org/project/pillow/) is optional and draws the
colorful category icons; without it the app shows plain emoji instead.

```
python -m pip install -r requirements.txt
```

## Desktop window

```
python main.py
```

- **Expenses** – quick-add form, list with icons, and a *By category* panel with subcategories,
  change vs the previous month and budget usage. Double-click (or right-click) an expense to edit,
  duplicate, attach a receipt or delete it. "More…" opens the full form.
- **Income** – salary, freelance, etc. The header shows income, expenses and balance for the month.
- **Charts** – spending by category (donut) and income vs expenses for the last 12 months.
- **Budgets** – monthly limit per category with progress bars (orange from 80%, red when over).
- **Recurring** – rent, subscriptions and bills. When one is due, the app asks to add it.
- **Period** – the picker at the top chooses a month ("September 2026"), a whole year
  ("2026 · whole year") or all months; ◀ ▶ step by month or by year.
- **Sorting** – click any column heading (category, date, amount, payment…) to sort; click
  again to reverse.
- **Filters** – category, payment method and tag (e.g. everything tagged `#cusco-trip`).
- **Search** (Ctrl+F) looks through all months by description, category, payment method or tag
  (`#tag` matches tags only).
- **File menu** – import a bank statement CSV (column mapping, `;` or `,`, `1.234,56` amounts,
  duplicates skipped), export CSV, back up now, open the data folder.
- **Settings menu** – categories & subcategories with icons and colors, payment methods,
  income sources. Renaming updates existing records.

## Currencies

Amounts are entered in PEN by default, or in USD. Every expense and income stores its own exchange
rate (soles per 1 US dollar) from the moment it was entered, so later rate changes never affect
older records. The rate field remembers the last rate you used. Use "Show in" to see everything
in PEN or USD.

## Command line

```
python -m expense_tracker                                   # interactive menu
python -m expense_tracker add 18 transport -s Taxi -p Yape -t work -d "Taxi to office" --rate 3.72
python -m expense_tracker add 12 books --currency USD       # reuses the last rate
python -m expense_tracker edit <id> --rate 3.80 -s Gasoline # only the given fields change
python -m expense_tracker list --month 2026-09 --in USD
python -m expense_tracker summary --month 2026-09
python -m expense_tracker income add 5200 salary
python -m expense_tracker budget set transport 250
python -m expense_tracker budget list
python -m expense_tracker export expenses.csv --month 2026-09
python -m expense_tracker backup
python -m expense_tracker users list
python -m expense_tracker users add "Oficina" --type Work
python -m expense_tracker --user Oficina list               # any command, for a specific user
```

Commands use the last user you opened unless you pass `--user NAME`. To work on a single file
directly instead, use `--file path/to/file.json` or the `EXPENSES_FILE` environment variable.

## Tests

```
python -m unittest -v
```
