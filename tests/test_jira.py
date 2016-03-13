import pytest
from mock import MagicMock, mock
import responses
import re
import json

from .common import controlled_responses, get_message
from plugins.jira import JiraBot, JiraNotifierBot
from utils.messages_cache import MessagesCache


with open('tests/test_jira_data.json') as data_file:
    data = json.load(data_file)

server = {'host': 'http://host', 'username': 'user', 'password': 'pass'}
prefixes = ['JIRA', 'JIRB']


@pytest.fixture
def bot():
    jiraBot = JiraBot(MessagesCache(), server, prefixes)
    return jiraBot


@pytest.mark.parametrize('input,expected', [
    ('', None),
    ('JIRA', None),
    ('JIRA-', None),
    ('JIRA-1234', 'JIRA-1234'),
    ('IRA-1234', None),
    ('SOMETHING JIRA-1234', 'JIRA-1234'),
    ('JIRA-1234 SOMETHING', 'JIRA-1234'),
    ('SOMETHING JIRA-1234 SOMETHING', 'JIRA-1234'),
    ('SOMETHINGJIRA-1234', None),
    ('JIRA-1234SOMETHING', None),
    ('CLEAN JIRA-1234', None),
])
def test_jirapattern(bot, input, expected):
    result = re.search(bot.get_pattern(), input, re.IGNORECASE)
    if expected is None:
        assert result == expected
    else:
        assert result.group(1) == expected


@pytest.mark.parametrize('input,testdata', [
                         ('JIRA-1 & JIRA-2', data['jirabot_result']),
                         ('JIRA-1 & JIRA-1', data['jirabot_result1']),
                         ('JIRA-3', data['jirabot_notexist']),
                         ])
def test_display_issues(bot, input, testdata):
    with controlled_responses(testdata['requests']) as rsps:
        rsps.rsps.add(
            responses.POST,
            'http://host/rest/auth/1/session',
            status=200)

        message = get_message(input)

        bot.display_issues(message)

        assert len(message.send_webapi.call_args_list) == 1
        args, kwargs = message.send_webapi.call_args_list[0]
        assert args[0] is ''
        assert json.loads(args[1]) == testdata['result']

        # Second call should not display message again
        message.send_webapi.reset_mock()
        bot.display_issues(message)
        assert not message.send_webapi.called


def test_wrong_auth(bot):
    with controlled_responses() as rsps:
        rsps.rsps.add(
            responses.POST,
            'http://host/rest/auth/1/session',
            status=401)

        message = get_message('JIRA-1')

        with pytest.raises(SystemExit):
            bot.display_issues(message)


@pytest.mark.parametrize('testdata', [(data['jiranotifier'])])
def test_notifier(testdata):
    slack_mock = MagicMock()
    slack_mock.channels = {'channel_id': {'name': 'atlassianbot-test'}}
    slack_mock.send_message = MagicMock()

    conf = {
        "polling_interval": 1,
        "notifiers":
        [
            {
                "query": "project = JIRA and status = Closed and issuetype not in subtaskIssueTypes()",
                "channel": "atlassianbot-test"
            }
        ]
    }

    with controlled_responses() as rsps:
        rsps.rsps.add(
            responses.POST,
            'http://host/rest/auth/1/session',
            status=200)

        rsps.rsps.add(
            responses.GET,
            re.compile(r'http?://host/rest/api/2/search.+'),
            status=200,
            body=json.dumps(testdata['requests'][0]['text']),
            content_type='application/json')

        rsps.rsps.add(
            responses.GET,
            re.compile(r'http?://host/rest/api/2/search.+'),
            status=200,
            body=json.dumps(testdata['requests'][0]['text']),
            content_type='application/json')

        obj = JiraNotifierBot(server, conf, slack_mock)

        # Wait the thread retrieve initial issue
        obj.thread_started.wait()

        slack_mock.send_message.assert_called_once_with(
                                                        'channel_id',
                                                        '',
                                                        attachments=mock.ANY)
        call = slack_mock.send_message.call_args
        call_args, call_kwargs = call
        assert testdata['result'] == json.loads(call_kwargs['attachments'])
