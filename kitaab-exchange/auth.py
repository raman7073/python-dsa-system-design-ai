from fastapi import Header, HTTPException

# in prod u add this to env
API_KEY = "my_secret_api_key"


def verify_api_key(x_api_key: str = Header()):
    """verify the api key from request header"""

    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    return x_api_key
