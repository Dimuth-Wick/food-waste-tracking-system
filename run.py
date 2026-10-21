"""Start the web app: python run.py, then open http://127.0.0.1:5000"""

import logging

import uvicorn

from app import create_app


app = create_app()


if __name__ == "__main__":
    # Show the app's own messages (such as camera captures) in the terminal.
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("app").setLevel(logging.INFO)
    uvicorn.run(app, host="127.0.0.1", port=5000)
