"""Hidden acceptance tests for bugfix-unit (copied into the workspace by the grader)."""
import base64
import unittest
from datetime import datetime, timedelta, timezone

from app import create_app, db
from app.models import User
from config import Config


class HiddenConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    ELASTICSEARCH_URL = None
    WTF_CSRF_ENABLED = False


class Base(unittest.TestCase):
    def setUp(self):
        self.app = create_app(HiddenConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.user = User(username='alice', email='alice@example.com')
        self.user.set_password('pw')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()


class TokenModel(Base):
    def test_valid_token_is_reused(self):
        t1 = self.user.get_token()
        db.session.commit()
        self.assertEqual(self.user.get_token(), t1)

    def test_revoked_token_is_rejected(self):
        t = self.user.get_token()
        db.session.commit()
        self.user.revoke_token()
        db.session.commit()
        self.assertIsNone(User.check_token(t))

    def test_new_token_after_revoke(self):
        t = self.user.get_token()
        db.session.commit()
        self.user.revoke_token()
        db.session.commit()
        t2 = self.user.get_token()
        self.assertNotEqual(t, t2)
        self.assertEqual(User.check_token(t2), self.user)

    def test_expired_token_is_not_handed_out_again(self):
        t = self.user.get_token()
        self.user.token_expiration = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.session.commit()
        self.assertIsNone(User.check_token(t))
        self.assertNotEqual(self.user.get_token(), t)

    def test_token_near_expiry_is_rotated(self):
        t = self.user.get_token()
        self.user.token_expiration = datetime.now(timezone.utc) + timedelta(seconds=30)
        db.session.commit()
        self.assertNotEqual(self.user.get_token(), t)


class TokenApi(Base):
    def test_revoke_via_api(self):
        c = self.app.test_client()
        basic = base64.b64encode(b'alice:pw').decode()
        r = c.post('/api/tokens', headers={'Authorization': f'Basic {basic}'})
        self.assertEqual(r.status_code, 200)
        token = r.get_json()['token']
        bearer = {'Authorization': f'Bearer {token}'}
        self.assertEqual(c.get(f'/api/users/{self.user.id}', headers=bearer).status_code, 200)
        self.assertEqual(c.delete('/api/tokens', headers=bearer).status_code, 204)
        self.assertEqual(c.get(f'/api/users/{self.user.id}', headers=bearer).status_code, 401)


if __name__ == '__main__':
    unittest.main()
