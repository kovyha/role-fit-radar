import pytest
import email
from email.mime.text import MIMEText
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def greenhouse_stubs_response():
    """Phase 1: /jobs list with 2 stubs — one London, one San Francisco. No content field."""
    return {
        "jobs": [
            {
                "id": 1001,
                "title": "Senior Quantitative Developer",
                "absolute_url": "https://www.anthropic.com/careers/1001",
                "location": {"name": "London, UK"},
                "departments": [{"name": "Engineering"}],
            },
            {
                "id": 1002,
                "title": "Product Manager",
                "absolute_url": "https://www.anthropic.com/careers/1002",
                "location": {"name": "San Francisco, USA"},
                "departments": [{"name": "Product"}],
            },
        ]
    }


@pytest.fixture
def greenhouse_detail_1001():
    """Phase 2: /jobs/1001?content=true detail response."""
    return {
        "id": 1001,
        "title": "Senior Quantitative Developer",
        "absolute_url": "https://www.anthropic.com/careers/1001",
        "location": {"name": "London, UK"},
        "departments": [{"name": "Engineering"}],
        "content": "<p>We are looking for a <strong>senior quant developer</strong>.</p><p>Requirements: 5+ years experience.</p>",
    }


@pytest.fixture
def greenhouse_api_empty():
    """Greenhouse API response with no jobs."""
    return {"jobs": []}


@pytest.fixture
def greenhouse_stubs_no_departments():
    """Phase 1 stub for a job with no departments."""
    return {
        "jobs": [
            {
                "id": 2001,
                "title": "Electronic Trading Developer",
                "absolute_url": "https://www.anthropic.com/careers/2001",
                "location": {"name": "London, UK"},
                "departments": [],
            }
        ]
    }


@pytest.fixture
def greenhouse_detail_2001():
    """Phase 2 detail for job 2001."""
    return {"id": 2001, "content": "Internship opportunity."}


@pytest.fixture
def greenhouse_stubs_long_content():
    """Phase 1 stub for a job whose description exceeds 6000 chars."""
    return {
        "jobs": [
            {
                "id": 3001,
                "title": "Algo Trading Engineer",
                "absolute_url": "https://example.com/role",
                "location": {"name": "London, UK"},
                "departments": [{"name": "Engineering"}],
            }
        ]
    }


@pytest.fixture
def greenhouse_detail_3001():
    """Phase 2 detail for job 3001 with content exceeding 6000 chars."""
    long_text = "Lorem ipsum dolor sit amet. " * 300  # ~8100 chars
    return {"id": 3001, "content": f"<p>{long_text}</p>"}


@pytest.fixture
def linkedin_email_html():
    """Sample LinkedIn job alert email HTML body with job cards."""
    return """
    <html>
    <body>
    <div class="email-content">
        <div class="job-card">
            <a href="https://www.linkedin.com/jobs/view/123456/?trackingId=abc">Senior Software Engineer</a>
            at Google • in London, UK
        </div>
        <div class="job-card">
            <a href="https://www.linkedin.com/jobs/view/789012/?trackingId=def">Product Manager</a>
            at Microsoft • in London, UK
        </div>
        <div class="job-card">
            <a href="https://www.linkedin.com/jobs/view/345678/?trackingId=ghi">Data Scientist</a>
            at Meta • in San Francisco, CA
        </div>
    </div>
    </body>
    </html>
    """


@pytest.fixture
def linkedin_email_no_jobs_html():
    """LinkedIn email without any job links."""
    return """
    <html>
    <body>
    <div class="email-content">
        <p>Hello, here are your job recommendations!</p>
        <p>No new matches this week.</p>
    </div>
    </body>
    </html>
    """


@pytest.fixture
def create_email_message():
    """Factory to create email.message.Message objects from HTML content."""
    def _create_message(html_content, is_multipart=False):
        if is_multipart:
            # Create multipart email with both text and HTML
            msg = email.message.EmailMessage()
            msg['Subject'] = 'LinkedIn Job Alerts'
            msg['From'] = 'jobalerts-noreply@linkedin.com'
            msg.set_content("Plain text version")
            msg.add_alternative(html_content, subtype='html')
            return msg
        else:
            # Simple HTML-only message
            msg = MIMEText(html_content, 'html')
            msg['Subject'] = 'LinkedIn Job Alerts'
            msg['From'] = 'jobalerts-noreply@linkedin.com'
            return msg
    return _create_message


@pytest.fixture
def mock_imap_connection():
    """Mock IMAP4_SSL connection object."""
    mock = MagicMock()

    # Mock mailbox list response
    mock.list.return_value = (
        'OK',
        [
            b'(\\All \\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "[Gmail]/All Mail"',
            b'(\\HasNoChildren) "/" "[Gmail]/JobSearch2026"'
        ]
    )

    # Mock select response
    mock.select.return_value = ('OK', [b'3'])

    # Mock search response (one message UID)
    mock.search.return_value = ('OK', [b'1'])

    # Create a simple RFC822 message
    from email.mime.text import MIMEText
    test_msg = MIMEText("<html><a href='https://linkedin.com/jobs/view/123'>Test Job</a></html>", 'html')
    test_msg['From'] = 'jobalerts-noreply@linkedin.com'
    msg_bytes = test_msg.as_bytes()

    mock.fetch.return_value = ('OK', [(None, msg_bytes)])
    mock.store.return_value = ('OK', None)
    mock.close.return_value = ('OK', None)
    mock.logout.return_value = ('OK', None)

    return mock


@pytest.fixture
def mock_playwright_page():
    """Mock Playwright page object for browser automation tests."""
    mock_page = AsyncMock()
    mock_page.set_extra_http_headers = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.query_selector_all = AsyncMock(return_value=[])
    mock_page.evaluate = AsyncMock(return_value="")
    mock_page.close = AsyncMock()
    return mock_page


@pytest.fixture
def mock_playwright_browser():
    """Mock Playwright browser object."""
    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock()
    mock_browser.close = AsyncMock()
    return mock_browser
