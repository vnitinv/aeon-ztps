from mock import patch

from aeon_ztp import ztp_celery


@patch('aeon_ztp.ztp_celery.socket')
def test_get_server_ipaddr(mock_socket):
    ip_addr = '1.1.1.1'
    af_inet = mock_socket.AF_INET = 2
    sock_dgram = mock_socket.SOCK_DGRAM = 2
    mock_socket.socket.return_value.getsockname.return_value = [ip_addr]
    s_ip = ztp_celery.get_server_ipaddr(ip_addr)
    mock_socket.socket.assert_called_with(af_inet, sock_dgram)
    mock_socket.socket.return_value.connect.assert_called_with((ip_addr, 0))
    mock_socket.socket.return_value.getsockname.assert_called()
    assert s_ip == ip_addr


@patch('aeon_ztp.ztp_celery.requests')
def test_post_device_status(mock_requests):
    os_name = 'test_os'
    target = '1.1.1.1'
    server = '2.2.2.2'
    state = 'excellent'
    message = 'test message'
    kw = {
        'message': message,
        'state': state
    }
    ztp_celery.post_device_status(server, target, os_name, **kw)
    mock_requests.put.assert_called_with(json={
        'message': message,
        'os_name': os_name,
        'ip_addr': target,
        'state': state
    },
        url='http://{}/api/devices/status'.format(server))
