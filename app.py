"""Mbare Musika: a beginner Python and Streamlit project."""
import csv
from datetime import date
from pathlib import Path
import streamlit as st

# A tuple holds fixed choices. All prices in this project are per kilogram.
PRODUCTS = ("Tomatoes", "Potatoes", "Onions", "Maize")
FILE_NAME = Path(__file__).parent / "prices.csv"


def load_prices():
    """Read a CSV file and return a list of dictionaries."""
    records = []
    try:
        with open(FILE_NAME, "r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                row["price"] = float(row["price"])
                if row["price"] <= 0:
                    raise ValueError("Prices must be greater than zero.")
                records.append(row)
    except FileNotFoundError:
        # No file yet is normal when starting for the first time.
        pass
    return records


def save_price(product, price, observed):
    """Append one observation. Write column names if the file is empty."""
    needs_header = not FILE_NAME.exists() or FILE_NAME.stat().st_size == 0
    with open(FILE_NAME, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if needs_header:
            writer.writerow(["date", "product", "price"])
        writer.writerow([observed, product, price])


# One simple class demonstrates objects, attributes and methods.
class Sale:
    def __init__(self, quantity, price, purchase_cost, transport_cost):
        self.quantity = quantity
        self.price = price
        self.purchase_cost = purchase_cost
        self.transport_cost = transport_cost

    def revenue(self):
        return self.quantity * self.price

    def profit(self):
        return self.revenue() - self.purchase_cost - self.transport_cost


st.set_page_config(page_title="Mbare Musika")
st.title("Mbare Musika")
st.write("A simple market price tracker and profit calculator.")
st.caption("Enter your own observations. No live market prices are connected.")

# A list supplies the navigation options.
menu = ["Dashboard", "Add Price", "Profit Calculator"]
page = st.sidebar.radio("Choose a page", menu)

try:
    prices = load_prices()
except (OSError, ValueError, KeyError, csv.Error) as error:
    st.error(f"Could not read prices.csv: {error}")
    st.stop()

if page == "Dashboard":
    st.header("Price Dashboard")
    st.metric("Saved observations", len(prices))

    # A set counts distinct products, even if a product appears many times.
    product_names = set()
    for record in prices:
        product_names.add(record["product"])
    st.metric("Different products", len(product_names))

    if len(prices) == 0:
        st.info("Choose Add Price to save your first observation.")
    else:
        selected = st.selectbox("Choose a product", PRODUCTS)
        matching = []
        total = 0
        for record in prices:
            if record["product"] == selected:
                matching.append(record)
                total = total + record["price"]

        if len(matching) > 0:
            average = total / len(matching)
            st.metric("Average recorded price per kg", f"US${average:.2f}")
            # Dates use YYYY-MM-DD, so normal string sorting orders them.
            matching = sorted(matching, key=lambda record: record["date"])
            st.table(matching)
            st.caption("Recorded prices in date order (one bar per observation).")
            chart_prices = []
            for record in matching:
                chart_prices.append(record["price"])
            st.bar_chart(chart_prices)
        else:
            st.info("No observations saved for this product yet.")

elif page == "Add Price":
    st.header("Add a Market Price")
    with st.form("price_form"):
        product = st.selectbox("Product", PRODUCTS)
        observed = st.date_input("Date observed", max_value=date.today())
        price = st.number_input("Price per kg (USD)", min_value=0.01, value=1.00, step=0.05)
        submitted = st.form_submit_button("Save Price")

    if submitted:
        try:
            save_price(product, price, str(observed))
            st.success(f"Saved {product.lower()} at US${price:.2f} per kg.")
        except (OSError, csv.Error) as error:
            st.error(f"Could not save the price: {error}")

elif page == "Profit Calculator":
    st.header("Profit Calculator")
    st.write("Use kilograms for quantity and a selling price per kilogram.")
    quantity = st.number_input("Quantity to sell (kg)", min_value=0.0, value=100.0)
    selling_price = st.number_input("Selling price per kg (USD)", min_value=0.0, value=1.0)
    purchase = st.number_input("Total purchase or production cost (USD)", min_value=0.0, value=40.0)
    transport = st.number_input("Total transport cost (USD)", min_value=0.0, value=10.0)

    if st.button("Calculate"):
        sale = Sale(quantity, selling_price, purchase, transport)
        revenue = sale.revenue()
        profit = sale.profit()
        st.metric("Revenue", f"US${revenue:.2f}")
        st.metric("Profit / loss", f"US${profit:.2f}")
        if profit > 0:
            st.success("The estimate shows a profit.")
        elif profit < 0:
            st.warning("The estimate shows a loss.")
        else:
            st.info("Revenue equals costs: break-even.")
