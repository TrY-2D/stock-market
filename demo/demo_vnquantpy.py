import os
import sys

sys.path.append(os.getcwd())

import vnquantpy

def demo():
    raw_data = vnquantpy.fetch_market_data(
        ticker={"exchange": "UPCOM", "symbol": "ACV"},
        interval="1d",
        auth_token=os.environ.get("TV_AUTH_TOKEN"),
        with_replay=False,
    )
    print(raw_data) 

if __name__ == "__main__":
    demo()