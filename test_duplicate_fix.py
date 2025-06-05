import sys
import os
sys.path.insert(0, '/home/natefsmith/Github/backblaze-snapshot-reporting')

# Mock the missing modules to avoid import errors
import unittest.mock as mock
sys.modules['redis'] = mock.MagicMock()

try:
    import app.app
    print('SUCCESS: Flask app imported without duplicate route errors!')
except AssertionError as e:
    if 'View function mapping is overwriting' in str(e):
        print(f'FAILED: Still have duplicate route error: {e}')
    else:
        print(f'FAILED: Different assertion error: {e}')
except Exception as e:
    print(f'Import had other errors (not duplicate routes): {type(e).__name__}: {e}') 