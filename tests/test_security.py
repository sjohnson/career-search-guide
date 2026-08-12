from app.services.security import hash_password, verify_password


class TestPasswordHashing:
    def test_hash_and_verify_round_trip(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert hashed != "correct-horse-battery-staple"
        assert verify_password("correct-horse-battery-staple", hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("secret-password")
        assert not verify_password("wrong-password", hashed)
