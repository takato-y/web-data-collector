"""FN-002 robots.txt 確認・FN-003 アクセス間隔制御のテスト。"""
from webcollector.politeness import RateLimiter, RobotsPolicy

UA = "WebDataCollector/1.0 (+https://example.com/bot-info)"
ROBOTS = "User-agent: *\nDisallow: /admin/\nCrawl-delay: 2\n"


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, sec):
        self.slept.append(round(sec, 3))
        self.now += sec


def test_rate_limiter_keeps_interval_per_host():
    c = FakeClock()
    rl = RateLimiter(clock=c.clock, sleep=c.sleep)
    rl.wait("a.example.com", 1.0)       # 初回は待たない
    c.now += 0.3
    rl.wait("a.example.com", 1.0)       # 残り 0.7 秒待つ
    rl.wait("b.example.com", 1.0)       # 別ホストは待たない
    c.now += 5
    rl.wait("a.example.com", 1.0)       # 十分経っていれば待たない
    assert c.slept == [0.7]


def test_robots_ok_disallow_and_crawl_delay():
    fetched = []

    def fetch(url):
        fetched.append(url)
        return 200, ROBOTS

    policy = RobotsPolicy(fetch, UA)
    assert policy.allowed("http://shop.example.com/products")
    assert not policy.allowed("http://shop.example.com/admin/")
    assert policy.interval_for("http://shop.example.com/products", 1.0) == 2.0
    assert policy.interval_for("http://shop.example.com/products", 3.0) == 3.0
    assert fetched == ["http://shop.example.com/robots.txt"]  # ホストごとに 1 回だけ取得


def test_robots_specific_agent_rule():
    policy = RobotsPolicy(lambda u: (200, "User-agent: WebDataCollector\nDisallow: /\n\nUser-agent: *\nAllow: /\n"), UA)
    assert not policy.allowed("http://shop.example.com/products")


def test_robots_missing_means_allowed():
    policy = RobotsPolicy(lambda u: (404, ""), UA)
    assert policy.allowed("http://shop.example.com/anything")
    assert not policy.is_unavailable("http://shop.example.com/")


def test_robots_unavailable_means_disallow_all():
    for status in (503, None):
        policy = RobotsPolicy(lambda u, s=status: (s, ""), UA)
        assert policy.is_unavailable("http://shop.example.com/")
        assert not policy.allowed("http://shop.example.com/products")
