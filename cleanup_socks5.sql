-- SQL script to remove all SOCKS5 proxy configuration entries from database
-- Run this script in your PostgreSQL database to clean up SOCKS5 proxy settings

-- Remove SOCKS5 configuration entries
DELETE FROM config WHERE key IN (
    'socks5_enabled',
    'socks5_host',
    'socks5_port',
    'socks5_user',
    'socks5_pass',
    'socks5_proxy'
);

-- Show what was removed (optional)
-- SELECT 'SOCKS5 cleanup completed' as status;
