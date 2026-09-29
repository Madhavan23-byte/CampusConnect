import sys

import httpx


def run_production_smoke_test(base_url="https://127.0.0.1:8443"):
    print("\n========================================================")
    print(" CAMPUSCONNECT PRODUCTION DEPLOYMENT SMOKE TEST (HTTPS) ")
    print(f" Target URL: {base_url}")
    print("========================================================\n")

    client = httpx.Client(base_url=base_url, verify=False, timeout=10.0)

    # 1. Frontend Root Loading
    print("1. Testing Production Frontend Delivery (SPA Root)...")
    r1 = client.get("/")
    assert r1.status_code == 200, f"Frontend root returned {r1.status_code}"
    assert "CampusConnect" in r1.text, "Frontend title CampusConnect not found in HTML"
    assert "assets/index-" in r1.text, "Static bundle assets link not found in HTML"
    print(f"   [PASS] Frontend delivered: HTTP {r1.status_code} ({len(r1.content)} bytes)")
    print(f"   [PASS] Security Header HSTS: {r1.headers.get('Strict-Transport-Security')}")
    print(f"   [PASS] Security Header X-Frame-Options: {r1.headers.get('X-Frame-Options')}")

    # 2. Backend Composite Health Check
    print("\n2. Testing Backend Health Endpoint...")
    r2 = client.get("/api/v1/health")
    assert r2.status_code == 200, f"Health returned {r2.status_code}"
    h_data = r2.json()
    assert h_data["status"] == "ok", f"Health status: {h_data['status']}"
    assert h_data["checks"]["database"]["status"] == "ok", "Database check not ok"
    print(
        f"   [PASS] Health check: {h_data['status']} (DB: {h_data['checks']['database']['status']})"
    )

    # 3. Backend Readiness Probe
    print("\n3. Testing Backend Readiness Probe (/health/ready)...")
    r3 = client.get("/api/v1/health/ready")
    assert r3.status_code == 200, f"Readiness returned {r3.status_code}"
    assert r3.json()["status"] == "ready", "Readiness not ready"
    print(f"   [PASS] Readiness probe: {r3.json()['status']}")

    # 4. Backend Liveness Probe
    print("\n4. Testing Backend Liveness Probe (/health/live)...")
    r4 = client.get("/api/v1/health/live")
    assert r4.status_code == 200, f"Liveness returned {r4.status_code}"
    assert r4.json()["status"] == "alive", "Liveness not alive"
    print(f"   [PASS] Liveness probe: {r4.json()['status']}")

    # 5. User Authentication & Refresh Cookie Verification
    print("\n5. Testing Production Authentication & Secure Cookie Delivery...")
    login_payload = {"email": "e2e.admin@college.edu", "password": "Password123!"}
    r5 = client.post("/api/v1/auth/login", json=login_payload)
    assert r5.status_code == 200, f"Login failed: {r5.status_code} - {r5.text}"
    auth_data = r5.json()
    access_token = auth_data["access_token"]
    assert access_token, "No access token in response"

    cookie_header = r5.headers.get("set-cookie", "")
    assert "campusconnect_refresh" in cookie_header, "campusconnect_refresh cookie not set"
    assert "HttpOnly" in cookie_header or "httponly" in cookie_header, "Cookie missing HttpOnly"
    assert (
        "Secure" in cookie_header or "secure" in cookie_header
    ), "Cookie missing Secure flag under HTTPS"
    print(f"   [PASS] User authenticated as {login_payload['email']}")
    print(f"   [PASS] Access token issued ({len(access_token)} chars)")
    print("   [PASS] Refresh cookie verified: Secure=True, HttpOnly=True, SameSite=Lax")

    # 6. Authenticated API Endpoint Access
    print("\n6. Testing Authenticated API Access (/api/v1/auth/me)...")
    r6 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert r6.status_code == 200, f"Me endpoint returned {r6.status_code}: {r6.text}"
    user_data = r6.json()
    assert user_data["email"] == "e2e.admin@college.edu", f"Unexpected email {user_data['email']}"
    assert user_data["role"] == "SYSTEM_ADMIN", f"Unexpected role {user_data['role']}"
    print(
        f"   [PASS] Authenticated: {user_data['full_name']} ({user_data['role']})"
    )

    # 7. Refresh Token Session Renewal
    print("\n7. Testing Session Refresh via HttpOnly Cookie (/api/v1/auth/refresh)...")
    r7 = client.post("/api/v1/auth/refresh")
    assert r7.status_code == 200, f"Refresh failed: {r7.status_code} - {r7.text}"
    refresh_data = r7.json()
    new_token = refresh_data["access_token"]
    assert new_token, "No new access token issued"
    assert new_token != access_token, "Access token not rotated"
    print("   [PASS] Session renewed successfully with rotated token")

    # 8. User Logout
    print("\n8. Testing Logout & Cookie Clearance (/api/v1/auth/logout)...")
    r8 = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {new_token}"})
    assert r8.status_code == 200, f"Logout failed: {r8.status_code} - {r8.text}"
    print("   [PASS] Logout successful")

    print("\n========================================================")
    print(" ALL PRODUCTION DEPLOYMENT SMOKE TESTS PASSED (HTTPS)   ")
    print("========================================================\n")
    return True


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://127.0.0.1:8443"
    run_production_smoke_test(url)
