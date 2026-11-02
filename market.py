"""Python domain classes for the Mbare Musika academic project.

The Streamlit UI composes these objects; calculations and persistence can
also run without a web interface (see demo_concepts.py).
"""
from datetime import date, timedelta
from pathlib import Path
import math
import random
import sqlite3
import pandas as pd

# A list preserves the order used by CSV and database records.
COLUMNS = ['date', 'commodity', 'unit', 'price_usd', 'source']
DB_PATH = Path(__file__).parent / 'data' / 'market.db'

class PriceValidationError(ValueError):
    """A specific, catchable error for invalid market observations."""

class PriceValidator:
    """Share validation between manual entry and file imports."""
    @staticmethod
    def validate(frame):
        missing = set(COLUMNS) - set(frame.columns)
        if missing:
            raise PriceValidationError('Missing columns: ' + ', '.join(sorted(missing)))
        result = frame[COLUMNS].copy()
        if result.empty:
            raise PriceValidationError('The file has no price records.')
        if len(result) > 10000:
            raise PriceValidationError('Upload at most 10,000 records at a time.')
        parsed = pd.to_datetime(result['date'], format='%Y-%m-%d', errors='coerce')
        if parsed.isna().any():
            raise PriceValidationError('Dates must be valid YYYY-MM-DD dates.')
        if (parsed.dt.date > date.today()).any():
            raise PriceValidationError('Price observations cannot have future dates.')
        result['date'] = parsed.dt.strftime('%Y-%m-%d')
        for field in ['commodity', 'unit', 'source']:
            if result[field].isna().any():
                raise PriceValidationError(f'{field} cannot be empty.')
            result[field] = result[field].astype(str).str.strip()
            if (result[field].str.len() == 0).any() or (result[field].str.len() > 120).any():
                raise PriceValidationError(f'{field} must contain 1–120 characters.')
        result['commodity'] = result['commodity'].str.title()
        result['unit'] = result['unit'].str.lower()
        result['price_usd'] = pd.to_numeric(result['price_usd'], errors='coerce')
        if not result['price_usd'].map(lambda p: math.isfinite(p) and p > 0).all():
            raise PriceValidationError('Prices must be finite numbers greater than zero.')
        return result.drop_duplicates(['date', 'commodity', 'unit', 'source'], keep='last')

class PriceRepository:
    """Encapsulate the SQLite database path and all database operations.

    _connect is an internal method by Python naming convention, not
    enforced private access. Values are bound to SQL placeholders.
    """
    def __init__(self, path=DB_PATH):
        self._path = Path(path)

    def _connect(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self._path, timeout=15)
        con.execute("""CREATE TABLE IF NOT EXISTS prices (
            date TEXT NOT NULL, commodity TEXT NOT NULL, unit TEXT NOT NULL,
            price_usd REAL NOT NULL CHECK(price_usd > 0), source TEXT NOT NULL,
            PRIMARY KEY (date, commodity, unit, source))""")
        return con

    def load(self):
        con = self._connect()
        try:
            return pd.read_sql_query('SELECT * FROM prices ORDER BY date, commodity', con)
        finally:
            con.close()

    def save(self, frame):
        clean = PriceValidator.validate(frame)
        con = self._connect()
        try:
            with con:
                # A list of tuples supplies positional records to SQLite.
                records = list(clean.itertuples(index=False, name=None))
                con.executemany("""INSERT INTO prices VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(date,commodity,unit,source)
                    DO UPDATE SET price_usd=excluded.price_usd""", records)
        finally:
            con.close()
        return len(clean)

class MarketAnalyzer:
    """Operate on a copy so analysis does not mutate caller-owned data."""
    def __init__(self, observations):
        self._observations = observations.copy()

    def commodity_units(self):
        # Each tuple binds a commodity to its unit; a set removes duplicates.
        return sorted(set(zip(self._observations['commodity'], self._observations['unit'])))

    def daily_prices(self):
        return self._observations.groupby(
            ['date', 'commodity', 'unit'], as_index=False)['price_usd'].median()

    def latest(self, commodity, unit):
        daily = self.daily_prices()
        matching = daily[(daily['commodity'] == commodity) & (daily['unit'] == unit)]
        if matching.empty:
            raise LookupError(f'No observations for {commodity} per {unit}.')
        return matching.sort_values('date').iloc[-1].to_dict()

class ProfitCalculator:
    """Hold one trip's assumptions and calculate results or scenarios."""
    def __init__(self, quantity, price, production, transport, fees, loss_pct):
        try:
            values = [float(v) for v in (quantity, price, production, transport, fees, loss_pct)]
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError('All trip inputs must be numbers.') from exc
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError('All inputs must be finite and non-negative.')
        if values[-1] > 100:
            raise ValueError('Loss percentage must be between 0 and 100.')
        self.quantity, self.price, self.production, self.transport, self.fees, self.loss_pct = values

    def estimate(self):
        quantity, price = self.quantity, self.price
        production, transport = self.production, self.transport
        fees, loss_pct = self.fees, self.loss_pct
        values = [quantity, price, production, transport, fees, loss_pct]
        if not all(math.isfinite(float(v)) and float(v) >= 0 for v in values):
            raise ValueError('All inputs must be finite and non-negative.')
        if loss_pct > 100:
            raise ValueError('Loss percentage must be between 0 and 100.')
        saleable = quantity * (1 - loss_pct / 100)
        cost = production + transport + fees
        revenue = saleable * price
        return dict(saleable=saleable, cost=cost, revenue=revenue,
                    profit=revenue-cost, break_even=cost/saleable if saleable else None,
                    margin=100*(revenue-cost)/revenue if revenue else None)

    def scenarios(self):
        results = []
        for label, multiplier in [('Price falls 20%', .8), ('Your expected price', 1), ('Price rises 20%', 1.2)]:
            scenario = ProfitCalculator(self.quantity, self.price * multiplier,
                self.production, self.transport, self.fees, self.loss_pct)
            results.append({'Scenario': label, 'Price / unit (USD)': round(scenario.price, 2),
                            'Net profit (USD)': round(scenario.estimate()['profit'], 2)})
        return results

class CsvHandler:
    """Read validated CSV observations and export spreadsheet-safe CSV."""
    @staticmethod
    def read(file_or_buffer):
        # Accepts Streamlit uploads, StringIO, or a file opened with 'with'.
        return PriceValidator.validate(pd.read_csv(file_or_buffer))

    @staticmethod
    def to_bytes(frame):
        """Escape spreadsheet formula prefixes in exported text cells."""
        safe = frame.copy()
        for column in safe.select_dtypes(include=['object', 'string']).columns:
            safe[column] = safe[column].map(
                lambda v: "'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v)
        return safe.to_csv(index=False).encode('utf-8')

    @classmethod
    def write(cls, frame, path):
        # The context manager closes the file even when writing fails.
        with Path(path).open('wb') as output:
            output.write(cls.to_bytes(frame))

def demo_prices():
    rng = random.Random(35)
    products = [('Tomatoes', 'kg', 0.85), ('Maize', 'kg', 0.35),
                ('Potatoes', 'kg', 0.65), ('Onions', 'kg', 0.80),
                ('Watermelons', 'each', 2.50), ('Eggs', 'tray of 30', 4.20)]
    rows = []
    for day in range(30):
        for item, unit, base in products:
            price = round(base * (1 + day * 0.003 + rng.uniform(-0.12, 0.12)), 2)
            rows.append([(date.today() - timedelta(days=29-day)).isoformat(),
                         item, unit, price, 'Synthetic demonstration'])
    return pd.DataFrame(rows, columns=COLUMNS)

# Small compatibility functions retain the original public API.
# The dashboard and command-line demonstration use the classes directly.
def validate_prices(frame):
    return PriceValidator.validate(frame)

def load_prices(path=DB_PATH):
    return PriceRepository(path).load()

def save_prices(frame, path=DB_PATH):
    return PriceRepository(path).save(frame)

def daily_prices(frame):
    return MarketAnalyzer(frame).daily_prices()

def profit_estimate(quantity, price, production, transport, fees, loss_pct):
    return ProfitCalculator(quantity, price, production, transport, fees, loss_pct).estimate()

def csv_bytes(frame):
    return CsvHandler.to_bytes(frame)
