from axes.backends import AxesStandaloneBackend


class RateLimitAxesBackend(AxesStandaloneBackend):
    """
    Axes rate-limiting backend that gracefully falls through if request is None
    (e.g., during programmatic authentication, management commands, or tests),
    preventing unhandled AxesBackendRequestParameterRequired exceptions.
    """

    def authenticate(self, request=None, **credentials):
        if request is None:
            return None
        return super().authenticate(request, **credentials)
