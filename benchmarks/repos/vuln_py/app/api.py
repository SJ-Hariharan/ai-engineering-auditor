from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import jwt

api = FastAPI()

# GT:fastapi_cors|cors-misconfig|CWE-942|yes
api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)

ITEMS = {}


def current_user():
    return {"id": 1}


@api.get("/items")
def list_items(user=Depends(current_user)):
    return list(ITEMS.values())


# SAFE:safe_auth_delete|missing-auth
@api.delete("/items/{item_id}")
def delete_item(item_id: int, user=Depends(current_user)):
    ITEMS.pop(item_id, None)
    return {"ok": True}


# GT:fastapi_noauth_delete|missing-auth|CWE-306|yes
@api.delete("/admin/items/{item_id}")
def admin_delete_item(item_id: int):
    ITEMS.pop(item_id, None)
    return {"ok": True}


# GT:fastapi_noauth_post|missing-auth|CWE-306|yes
@api.post("/admin/items")
def admin_create_item(item: dict):
    ITEMS[len(ITEMS)] = item
    return item


def verify(token: str):
    # GT:jwt_noverify_alg_none|jwt-verification|CWE-347|yes
    return jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256"])
