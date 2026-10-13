import re
from datetime import datetime
from urllib.parse import quote

import requests
from django.db import models
from django.utils.html import urlize
from django.utils.timezone import make_aware, utc
from django.utils.translation import gettext_lazy as _
from requests_oauthlib import OAuth1

from mezzanine.conf import settings
from mezzanine.twitter import QUERY_TYPE_CHOICES, get_auth_settings
from mezzanine.twitter.managers import TweetManager
from mezzanine.twitter.strategies import get_strategy

re_usernames = re.compile(r"(^|\W)@([0-9a-zA-Z+_]+)", re.IGNORECASE)
re_hashtags = re.compile(r"#([0-9a-zA-Z+_]+)", re.IGNORECASE)
replace_hashtags = '<a href="http://twitter.com/search?q=%23\\1">#\\1</a>'
replace_usernames = '\\1<a href="http://twitter.com/\\2">@\\2</a>'


# Date format used by the Twitter API for ``created_at``.
TWEET_DATE_FORMAT = "%a %b %d %H:%M:%S +0000 %Y"


class TwitterQueryException(Exception):
    pass


class Query(models.Model):

    type = models.CharField(_("Type"), choices=QUERY_TYPE_CHOICES, max_length=10)
    value = models.CharField(_("Value"), max_length=140)
    interested = models.BooleanField("Interested", default=True)

    class Meta:
        verbose_name = _("Twitter query")
        verbose_name_plural = _("Twitter queries")
        ordering = ("-id",)

    def __str__(self):
        return f"{self.get_type_display()}: {self.value}"

    def run(self):
        """
        Request new tweets from the Twitter API.

        The steps that depend on the query type (building the URL and
        extracting the tweets from the payload) are delegated to the
        ``QueryStrategy`` registered for ``self.type``. Authentication,
        the HTTP request, error handling and saving tweets are shared
        by every type.
        """
        try:
            strategy = get_strategy(self.type)
        except KeyError:
            raise TwitterQueryException("Invalid query type: %s" % self.type)
        try:
            value = quote(self.value)
        except KeyError:
            value = self.value
        payload = self._fetch(strategy.build_url(value))
        for tweet_json in strategy.extract_tweets(payload):
            self._save_tweet(tweet_json)
        self.interested = False
        self.save()

    def _get_auth_settings(self):
        """
        Returns the OAuth credentials: the configured settings, or
        the read-only default keys when nothing has been configured
        and this is the default query.
        """
        auth_settings = get_auth_settings()
        if auth_settings:
            return auth_settings
        from mezzanine.conf import registry

        if self.value == registry["TWITTER_DEFAULT_QUERY"]["default"]:
            # These are some read-only keys and secrets we use
            # for the default query (eg nothing has been configured)
            return (
                "KxZTRD3OBft4PP0iQW0aNQ",
                "sXpQRSDUVJ2AVPZTfh6MrJjHfOGcdK4wRb1WTGQ",
                "1368725588-ldWCsd54AJpG2xcB5nyTHyCeIC3RJcNVUAkB1OI",
                "r9u7qS18t8ad4Hu9XVqmCGxlIpzoCN3e1vx6LOSVgyw3R",
            )
        raise TwitterQueryException("Twitter OAuth settings missing")

    def _fetch(self, url):
        """
        Performs the authenticated API request and returns the decoded
        payload, raising ``TwitterQueryException`` on transport errors
        or when the API reports an error.
        """
        auth_settings = self._get_auth_settings()
        try:
            payload = requests.get(url, auth=OAuth1(*auth_settings)).json()
        except Exception as e:
            raise TwitterQueryException("Error retrieving: %s" % e)
        try:
            raise TwitterQueryException(payload["errors"][0]["message"])
        except (IndexError, KeyError, TypeError):
            pass
        return payload

    def _save_tweet(self, tweet_json):
        """
        Creates a ``Tweet`` for the given API tweet dict, unless it
        has already been stored for this query.
        """
        remote_id = str(tweet_json["id"])
        tweet, created = self.tweets.get_or_create(remote_id=remote_id)
        if not created:
            return
        if "retweeted_status" in tweet_json:
            user = tweet_json["user"]
            tweet.retweeter_user_name = user["screen_name"]
            tweet.retweeter_full_name = user["name"]
            tweet.retweeter_profile_image_url = user["profile_image_url"]
            tweet_json = tweet_json["retweeted_status"]
        user = tweet_json["user"]
        tweet.user_name = user["screen_name"]
        tweet.full_name = user["name"]
        tweet.profile_image_url = user["profile_image_url"]
        tweet.text = urlize(tweet_json["text"])
        tweet.text = re_usernames.sub(replace_usernames, tweet.text)
        tweet.text = re_hashtags.sub(replace_hashtags, tweet.text)
        if getattr(settings, "TWITTER_STRIP_HIGH_MULTIBYTE", False):
            chars = [ch for ch in tweet.text if ord(ch) < 0x800]
            tweet.text = "".join(chars)
        d = datetime.strptime(tweet_json["created_at"], TWEET_DATE_FORMAT)
        tweet.created_at = make_aware(d, utc)
        try:
            tweet.save()
        except Warning:
            pass
        tweet.save()


class Tweet(models.Model):

    remote_id = models.CharField(_("Twitter ID"), max_length=50)
    created_at = models.DateTimeField(_("Date/time"), null=True)
    text = models.TextField(_("Message"), null=True)
    profile_image_url = models.URLField(_("Profile image URL"), null=True)
    user_name = models.CharField(_("User name"), max_length=100, null=True)
    full_name = models.CharField(_("Full name"), max_length=100, null=True)
    retweeter_profile_image_url = models.URLField(
        _("Profile image URL (Retweeted by)"), null=True
    )
    retweeter_user_name = models.CharField(
        _("User name (Retweeted by)"), max_length=100, null=True
    )
    retweeter_full_name = models.CharField(
        _("Full name (Retweeted by)"), max_length=100, null=True
    )
    query = models.ForeignKey("Query", on_delete=models.CASCADE, related_name="tweets")

    objects = TweetManager()

    class Meta:
        verbose_name = _("Tweet")
        verbose_name_plural = _("Tweets")
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.user_name}: {self.text}"

    def is_retweet(self):
        return self.retweeter_user_name is not None
