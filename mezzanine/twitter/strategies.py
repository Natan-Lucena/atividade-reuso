"""
Strategies for the different types of Twitter queries (Strategy pattern).

``Query.run()`` delegates to one of these objects the two steps that
vary per query type: building the API URL for the query value, and
extracting the list of tweets from the API payload. Everything else
(authentication, HTTP request, error handling, saving tweets) is the
same for every type and stays in ``Query``.

To support a new type of query, add a ``QueryStrategy`` subclass and
register it in ``STRATEGIES``; ``Query`` doesn't need to change.
"""
from mezzanine.twitter import QUERY_TYPE_LIST, QUERY_TYPE_SEARCH, QUERY_TYPE_USER

API_ROOT = "https://api.twitter.com/1.1/"


class QueryStrategy:
    """
    Interface for a query type. ``build_url`` must be implemented;
    ``extract_tweets`` can be overridden when the API wraps the
    tweets inside the payload instead of returning a plain list.
    """

    def build_url(self, value):
        """
        Returns the API URL for the (already URL-quoted) query value.
        """
        raise NotImplementedError

    def extract_tweets(self, payload):
        """
        Returns the list of tweet dicts contained in the API payload.
        """
        return payload


class UserTimelineStrategy(QueryStrategy):
    """
    Tweets posted by a single user.
    """

    def build_url(self, value):
        return (
            API_ROOT + "statuses/user_timeline.json?screen_name=%s"
            "&include_rts=true" % value.lstrip("@")
        )


class ListStrategy(QueryStrategy):
    """
    Tweets posted by the members of a list.
    """

    def build_url(self, value):
        return API_ROOT + "lists/statuses.json?list_id=%s&include_rts=true" % value


class SearchStrategy(QueryStrategy):
    """
    Tweets matching a search term. The search endpoint wraps the
    tweets in a ``statuses`` key.
    """

    def build_url(self, value):
        return API_ROOT + "search/tweets.json?q=%s" % value

    def extract_tweets(self, payload):
        return payload["statuses"]


STRATEGIES = {
    QUERY_TYPE_USER: UserTimelineStrategy(),
    QUERY_TYPE_LIST: ListStrategy(),
    QUERY_TYPE_SEARCH: SearchStrategy(),
}


def get_strategy(query_type):
    """
    Returns the strategy registered for ``query_type``. Raises
    ``KeyError`` for unknown types.
    """
    return STRATEGIES[query_type]
