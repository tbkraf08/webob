import warnings
import re, textwrap
from datetime import datetime, date

from webob.headers import normalize_header as norm, _trans_name as header_to_key
from webob.byterange import Range, ContentRange
from webob.etag import AnyETag, NoETag, ETagMatcher, IfRange, NoIfRange
from webob.datetime_utils import serialize_date
from webob.acceptparse import Accept, NilAccept


CHARSET_RE = re.compile(r';\s*charset=([^;]*)', re.I)
QUOTES_RE = re.compile('"(.*)"')
SCHEME_RE = re.compile(r'^[a-z]+:', re.I)


_not_given = object()

def environ_getter(key, default=_not_given, rfc_section=None):
    doc = "Gets and sets the %r key in the environment." % key
    doc += _rfc_reference(key, rfc_section)
    if default is _not_given:
        def fget(req):
            return req.environ[key]
        fdel = None
    else:
        def fget(req):
            return req.environ.get(key, default)
        def fdel(req):
            del req.environ[key]
    def fset(req, val):
        req.environ[key] = val
    return property(fget, fset, fdel, doc=doc)



def header_getter(header, rfc_section):
    doc = "Gets and sets and deletes the %s header." % header
    doc += _rfc_reference(header, rfc_section)
    key = norm(header)

    def fget(r):
        for k, v in r._headerlist:
            if norm(k) == key:
                return v

    def fset(r, value):
        fdel(r)
        if value is not None:
            if isinstance(value, unicode):
                # This is the standard encoding for headers:
                value = value.encode('ISO-8859-1')
            r._headerlist.append((header, value))

    def fdel(r):
        items = r._headerlist
        for i in range(len(items)-1, -1, -1):
            if norm(items[i][0]) == key:
                del items[i]

    return property(fget, fset, fdel, doc)


def _rfc_reference(header, section):
    if not section:
        return ''
    major_section = section.split('.')[0]
    link = 'http://www.w3.org/Protocols/rfc2616/rfc2616-sec%s.html#sec%s' % (
        major_section, section)
    if header.startswith('HTTP_'):
        header = header[5:].title().replace('_', '-')
    return " For more information on %s see `section %s <%s>`_." % (
        header, section, link)


def converter(prop, parse, serialize, convert_name=None, converter_args=()):
    assert isinstance(prop, property)
    doc = prop.__doc__ or ''
    doc += "  Converts it as a "
    if convert_name:
        doc += convert_name + '.'
    else:
        doc += "%r and %r." % (parse, serialize)
    hget, hset = prop.fget, prop.fset
    if converter_args:
        def fget(r):
            return parse(hget(r), *converter_args)
        def fset(r, val):
            if val is not None:
                val = serialize(val, *converter_args)
            hset(r, val)
    else:
        def fget(r):
            return parse(hget(r))
        def fset(r, val):
            if val is not None:
                val = serialize(val)
            hset(r, val)
    return property(fget, fset, prop.fdel, doc)





def etag_property(key, default, rfc_section):
    prop = environ_getter(key, None, rfc_section)
    return converter(prop, parse_etag, serialize_etag, 'ETag', converter_args=(default,))


def accept_property(header, rfc_section,
    AcceptClass=Accept, NilClass=NilAccept, convert_name='accept header'
):
    key = header_to_key(header)
    prop = environ_getter(key, None, rfc_section)
    return converter(prop, parse_accept, serialize_accept, convert_name,
        converter_args=(header, AcceptClass, NilClass)
    )







class deprecated_property(object):
    """
    Wraps a descriptor, with a deprecation warning or error
    """
    def __init__(self, descriptor, attr, message, warning=True):
        self.descriptor = descriptor
        self.attr = attr
        self.message = message
        self.warning = warning

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        self.warn()
        return self.descriptor.__get__(obj, type)

    def __set__(self, obj, value):
        self.warn()
        self.descriptor.__set__(obj, value)

    def __delete__(self, obj):
        self.warn()
        self.descriptor.__delete__(obj)

    def __repr__(self):
        return '<Deprecated attribute %s: %r>' % (
            self.attr,
            self.descriptor)

    def warn(self):
        if not self.warning:
            raise DeprecationWarning(
                'The attribute %s is deprecated: %s' % (self.attr, self.message))
        else:
            warnings.warn(
                'The attribute %s is deprecated: %s' % (self.attr, self.message),
                DeprecationWarning,
                stacklevel=3)


class UnicodePathProperty(object):
    """
        upath_info and uscript_name descriptor implementation
    """

    def __init__(self, key):
        self.key = key

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        str_path = obj.environ[self.key]
        return str_path.decode('UTF8', obj.unicode_errors)

    def __set__(self, obj, path):
        if not isinstance(path, unicode):
            path = path.decode('ASCII') # or just throw an error?
        str_path = path.encode('UTF8', obj.unicode_errors)
        obj.environ[self.key] = str_path

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.key)



########################
## Converter functions
########################






def parse_etag(value, default=True):
    if value is None:
        value = ''
    value = value.strip()
    if not value:
        if default:
            return AnyETag
        else:
            return NoETag
    if value == '*':
        return AnyETag
    else:
        return ETagMatcher.parse(value)

def serialize_etag(value, default=True):
    if value is AnyETag:
        if default:
            return None
        else:
            return '*'
    return str(value)

# FIXME: weak entity tags are not supported, would need special class
def parse_etag_response(value):
    """
    See:
        * http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.19
        * http://www.w3.org/Protocols/rfc2616/rfc2616-sec3.html#sec3.11
    """
    if value is not None:
        unquote_match = QUOTES_RE.match(value)
        if unquote_match is not None:
            value = unquote_match.group(1)
            value = value.replace('\\"', '"')
        return value

def serialize_etag_response(value):
    return '"%s"' % value.replace('"', '\\"')

def parse_if_range(value):
    if not value:
        return NoIfRange
    else:
        return IfRange.parse(value)

def serialize_if_range(value):
    if isinstance(value, (datetime, date)):
        return serialize_date(value)
    if not isinstance(value, str):
        value = str(value)
    return value or None

def parse_range(value):
    if not value:
        return None
    # Might return None too:
    return Range.parse(value)

def serialize_range(value):
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError(
                "If setting .range to a list or tuple, it must be of length 2 (not %r)"
                % value)
        value = Range([value])
    if value is None:
        return None
    value = str(value)
    return value or None

def parse_int(value):
    if value is None or value == '':
        return None
    return int(value)

def parse_int_safe(value):
    if value is None or value == '':
        return None
    try:
        return int(value)
    except ValueError:
        return None

serialize_int = str

def parse_content_range(value):
    if not value or not value.strip():
        return None
    # May still return None
    return ContentRange.parse(value)

def serialize_content_range(value):
    if isinstance(value, (tuple, list)):
        if len(value) not in (2, 3):
            raise ValueError(
                "When setting content_range to a list/tuple, it must "
                "be length 2 or 3 (not %r)" % value)
        if len(value) == 2:
            begin, end = value
            length = None
        else:
            begin, end, length = value
        value = ContentRange(begin, end, length)
    value = str(value).strip()
    if not value:
        return None
    return value

def parse_list(value):
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return [v.strip() for v in value.split(',')
            if v.strip()]

def serialize_list(value):
    if isinstance(value, unicode):
        value = str(value)
    if isinstance(value, str):
        return value
    return ', '.join(map(str, value))

def parse_accept(value, header_name, AcceptClass, NilClass):
    if not value:
        return NilClass(header_name)
    return AcceptClass(header_name, value)

def serialize_accept(value, header_name, AcceptClass, NilClass):
    if not value or isinstance(value, NilClass): #@@ make bool(NilClass()) == False
        return None
    if isinstance(value, (list, tuple, dict)):
        value = NilClass(header_name) + value
    value = str(value).strip()
    if not value:
        return None
    return value

_rx_auth_param = re.compile(r'([a-z]+)=(".*?"|[^,]*)(?:\Z|, *)')

def parse_auth_params(params):
    r = {}
    for k, v in _rx_auth_param.findall(params):
        r[k] = v.strip('"')
    return r

# see http://lists.w3.org/Archives/Public/ietf-http-wg/2009OctDec/0297.html
known_auth_schemes = ['Basic', 'Digest', 'WSSE', 'HMACDigest', 'GoogleLogin', 'Cookie', 'OpenID']
known_auth_schemes = dict.fromkeys(known_auth_schemes, None)

def parse_auth(val):
    if val is not None:
        authtype, params = val.split(' ', 1)
        if authtype in known_auth_schemes:
            if authtype == 'Basic' and '"' not in params:
                # this is the "Authentication: Basic XXXXX==" case
                pass
            else:
                params = parse_auth_params(params)
        return authtype, params
    return val

def serialize_auth(val):
    if isinstance(val, (tuple, list)):
        authtype, params = val
        if isinstance(params, dict):
            params = ', '.join(map('%s="%s"'.__mod__, params.items()))
        assert isinstance(params, str)
        return '%s %s' % (authtype, params)
    return val
