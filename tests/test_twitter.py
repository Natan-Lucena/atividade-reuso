"""
Characterisation tests for ``Query.run()`` in ``mezzanine.twitter``.

They were written against the original implementation (before the
Strategy refactoring) and pin down its observable behaviour: the URL
requested for each query type, how tweets are extracted from the
payload, how a ``Tweet`` is populated, and every error path. The
Twitter API is never reached: ``requests.get`` is mocked.
"""
from datetime import datetime, timezone
from unittest import mock

from mezzanine.twitter import QUERY_TYPE_LIST, QUERY_TYPE_SEARCH, QUERY_TYPE_USER
from mezzanine.twitter.models import Query, TwitterQueryException
from mezzanine.utils.tests import TestCase

AUTH = ("consumer-key", "consumer-secret", "token-key", "token-secret")
CREATED_AT = "Mon Oct 13 10:00:00 +0000 2026"
REQUESTS_GET = "mezzanine.twitter.models.requests.get"
AUTH_SETTINGS = "mezzanine.twitter.models.get_auth_settings"


def tweet_json(remote_id, screen_name="stephen_mcd", name="Stephen McDonald"):
    """
    Minimal tweet as returned by the Twitter 1.1 API.
    """
    return {
        "id": remote_id,
        "text": "Hello @mezzanine #django http://example.com",
        "created_at": CREATED_AT,
        "user": {
            "screen_name": screen_name,
            "name": name,
            "profile_image_url": "http://example.com/%s.png" % screen_name,
        },
    }


class TwitterQueryTests(TestCase):
    def run_query(self, query, payload):
        """
        Runs ``query`` with the API mocked to return ``payload`` and
        returns the ``requests.get`` mock so the URL can be inspected.
        """
        response = mock.Mock()
        response.json.return_value = payload
        with mock.patch(AUTH_SETTINGS, return_value=AUTH):
            with mock.patch(REQUESTS_GET, return_value=response) as get:
                query.run()
        query.refresh_from_db()
        return get

    def requested_url(self, get):
        return get.call_args[0][0]

    def test_user_query(self):
        query = Query.objects.create(type=QUERY_TYPE_USER, value="stephen_mcd")
        get = self.run_query(query, [tweet_json(1), tweet_json(2)])
        self.assertIn(
            "statuses/user_timeline.json?screen_name=stephen_mcd&include_rts=true",
            self.requested_url(get),
        )
        self.assertEqual(query.tweets.count(), 2)
        self.assertFalse(query.interested)

    def test_list_query(self):
        query = Query.objects.create(type=QUERY_TYPE_LIST, value="12345")
        get = self.run_query(query, [tweet_json(1)])
        self.assertIn(
            "lists/statuses.json?list_id=12345&include_rts=true",
            self.requested_url(get),
        )
        self.assertEqual(query.tweets.count(), 1)

    def test_search_query_reads_statuses(self):
        query = Query.objects.create(type=QUERY_TYPE_SEARCH, value="mezzanine django")
        payload = {"statuses": [tweet_json(1), tweet_json(2), tweet_json(3)]}
        get = self.run_query(query, payload)
        self.assertIn(
            "search/tweets.json?q=mezzanine%20django", self.requested_url(get)
        )
        self.assertEqual(query.tweets.count(), 3)

    def test_tweet_fields(self):
        query = Query.objects.create(type=QUERY_TYPE_USER, value="stephen_mcd")
        self.run_query(query, [tweet_json(42)])
        tweet = query.tweets.get()
        self.assertEqual(tweet.remote_id, "42")
        self.assertEqual(tweet.user_name, "stephen_mcd")
        self.assertEqual(tweet.full_name, "Stephen McDonald")
        self.assertEqual(tweet.profile_image_url, "http://example.com/stephen_mcd.png")
        self.assertEqual(
            tweet.created_at, datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)
        )
        # Usernames, hashtags and URLs are turned into links.
        self.assertIn('<a href="http://twitter.com/mezzanine">@mezzanine</a>', tweet.text)
        self.assertIn(
            '<a href="http://twitter.com/search?q=%23django">#django</a>', tweet.text
        )
        self.assertIn('href="http://example.com"', tweet.text)
        self.assertFalse(tweet.is_retweet())

    def test_retweet(self):
        original = tweet_json(1, screen_name="original", name="Original Author")
        retweet = tweet_json(2, screen_name="retweeter", name="Re Tweeter")
        retweet["retweeted_status"] = original
        query = Query.objects.create(type=QUERY_TYPE_USER, value="retweeter")
        self.run_query(query, [retweet])
        tweet = query.tweets.get()
        self.assertEqual(tweet.remote_id, "2")
        self.assertEqual(tweet.user_name, "original")
        self.assertEqual(tweet.full_name, "Original Author")
        self.assertEqual(tweet.retweeter_user_name, "retweeter")
        self.assertEqual(tweet.retweeter_full_name, "Re Tweeter")
        self.assertEqual(
            tweet.retweeter_profile_image_url, "http://example.com/retweeter.png"
        )
        self.assertTrue(tweet.is_retweet())

    def test_existing_tweets_are_not_duplicated(self):
        query = Query.objects.create(type=QUERY_TYPE_USER, value="stephen_mcd")
        self.run_query(query, [tweet_json(1)])
        self.run_query(query, [tweet_json(1), tweet_json(2)])
        self.assertEqual(
            sorted(query.tweets.values_list("remote_id", flat=True)), ["1", "2"]
        )

    def test_invalid_query_type(self):
        query = Query.objects.create(type="bogus", value="whatever")
        with mock.patch(REQUESTS_GET) as get:
            with self.assertRaises(TwitterQueryException) as raised:
                query.run()
        self.assertEqual(str(raised.exception), "Invalid query type: bogus")
        get.assert_not_called()

    def test_missing_auth_settings(self):
        query = Query.objects.create(type=QUERY_TYPE_USER, value="someone")
        with mock.patch(AUTH_SETTINGS, return_value=None):
            with mock.patch(REQUESTS_GET) as get:
                with self.assertRaises(TwitterQueryException) as raised:
                    query.run()
        self.assertEqual(str(raised.exception), "Twitter OAuth settings missing")
        get.assert_not_called()

    def test_api_error_is_raised(self):
        query = Query.objects.create(type=QUERY_TYPE_SEARCH, value="anything")
        payload = {"errors": [{"message": "Rate limit exceeded", "code": 88}]}
        with self.assertRaises(TwitterQueryException) as raised:
            self.run_query(query, payload)
        self.assertEqual(str(raised.exception), "Rate limit exceeded")
        self.assertEqual(query.tweets.count(), 0)

    def test_request_failure_is_wrapped(self):
        query = Query.objects.create(type=QUERY_TYPE_USER, value="someone")
        with mock.patch(AUTH_SETTINGS, return_value=AUTH):
            with mock.patch(REQUESTS_GET, side_effect=OSError("connection refused")):
                with self.assertRaises(TwitterQueryException) as raised:
                    query.run()
        self.assertEqual(str(raised.exception), "Error retrieving: connection refused")
