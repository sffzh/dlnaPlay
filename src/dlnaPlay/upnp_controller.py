# this module mostly come from the project [flyte/upnpclient]
# I picked some functions out and intergrated them here, 
# so that I can kick out some dependencies such as lxml which may prevent me from install in some certain devices.
from abc import ABC, abstractmethod
import requests
import re
import datetime
from decimal import Decimal
from base64 import b64decode
from binascii import unhexlify
from collections import OrderedDict

import requests
from requests.compat import urljoin, urlparse
from dateutil.parser import parse as parse_date
from dlnaPlay._logger import get_logger
from dlnaPlay.soap import SOAP
from dlnaPlay import upnp_parser, marshal

logger = get_logger(__name__)
DEVICE_LOGGER = get_logger("Device")
SERVICE_LOGGER = get_logger("Service")
ACTION_LOGGER=get_logger("Action")

HTTP_TIMEOUT = 10


class UPNPError(Exception):
    pass

class ValidationError(UPNPError):
    """
    Given value didn't validate with the given data type.
    """
    def __init__(self, reasons):
        super(ValidationError, self).__init__()
        self.reasons = reasons

class InvalidActionException(UPNPError):
    def __init__(self, action_name:str, msg:str="") -> None:
        super().__init__(f"Action with name {action_name!r} does not exist.{msg}")
    
class UnexpectedResponse(UPNPError):
    """
    Got a response we didn't expect.
    """
    pass

class AbstAction(ABC):
    @abstractmethod
    def __call__(self, **kwargs)->dict:
        pass
    
class CallActionMixin(ABC):
    @abstractmethod
    def find_action(self, action_name)->AbstAction:
        pass
    def __call__(self, action_name, **kwargs):
        """
        Convenience method for quickly finding and calling an Action on a
        Service. Must have implemented a `find_action(action_name)` method.
        """
        action = self.find_action(action_name)
        if action is not None:
            return action(**kwargs)
        raise InvalidActionException(action_name, 'Failed to Call')

class Device(upnp_parser.UPnPDevice, CallActionMixin):
    """
    UPNP Device represention.
    This class represents an UPnP device. `location` is an URL to a control XML
    file, per UPnP standard section 2.3 ('Device Description'). This MUST match
    the URL as given in the 'Location' header when using discovery (SSDP).
    `device_name` is a name for the device, which may be obtained using the
    SSDP class or may be made up by the caller.

    Raises urllib2.HTTPError when the location is invalid

    Example:

    >>> device = Device('http://192.168.1.254:80/upnp/IGD.xml')
    >>> for service in device.services:
    ...     print service.service_id
    ...
    urn:upnp-org:serviceId:layer3f
    urn:upnp-org:serviceId:wancic
    urn:upnp-org:serviceId:wandsllc:pvc_Internet
    urn:upnp-org:serviceId:wanipc:Internet
    """

    def __init__(
        self,
        location,
        device_name=None,
        ignore_urlbase=False,
        http_auth=None,
        http_headers=None,
    ):
        """
        Create a new Device instance. `location` is an URL to an XML file
        describing the server's services.
        """
        
        self.location = location
        self.device_name = location if device_name is None else device_name
        self.services = []
        self.service_map = {}

        self.http_auth = http_auth
        self.http_headers = http_headers

        resp = requests.get(
            location, timeout=HTTP_TIMEOUT, auth=self.http_auth, headers=self.http_headers
        )
        resp.raise_for_status()
        xml = resp.content.decode('utf-8', errors='replace')
        upnp = upnp_parser.parse_upnp_device_description(xml)

        super().__init__(**vars(upnp))

        self._url_base:str = upnp.url_base or ""
        if not self._url_base or ignore_urlbase:
            # If no URL Base is given, the UPnP specification says: "the base
            # URL is the URL from which the device description was retrieved"
            self._url_base = self.location

    # lazyload service_map    
    def _service_map(self):
        if not self.service_map:
            self.service_map = {service.name: Service(self, service) for service in self.services}
        return self.service_map
    
    def __repr__(self):
        return "<Device '%s'>" % (self.friendly_name)

    def __getattr__(self, name):
        """
        Allow Services to be returned as members of the Device.
        """
        try:
            return self._service_map()[name]
        except KeyError:
            raise AttributeError("No attribute or service found with name %r." % name)

    def __getitem__(self, key):
        """
        Allow Services to be returned as dictionary keys of the Device.
        """
        return self._service_map()[key]

    def __dir__(self):
        """
        Add Service names to `dir(device)` output for use with tab-completion in repl.
        """
        return list(super(Device, self).__dir__()) + list(self._service_map().keys())

    @property
    def actions(self):
        actions = []
        for service in self._service_map().values():
            actions.extend(service.actions)
        return actions

    def find_action(self, action_name):
        """Find an action by name.
        Convenience method that searches through all the services offered by
        the Server for an action and returns an Action instance. If the action
        is not found, returns None. If multiple actions with the same name are
        found it returns the first one.
        """
        for service in self._service_map().values():
            action = service.find_action(action_name)
            if action is not None:
                return action
        raise InvalidActionException(action_name, '查找 Action')

class Service(CallActionMixin, upnp_parser.UPnPService):
    """
    Service Control Point Definition. This class reads an SCPD XML file and
    parses the actions and state variables. It can then be used to call
    actions.
    """

    def __init__(
        self,
        device:Device,
        service:upnp_parser.UPnPService
                ):
        super().__init__(**vars(service))
         
        self.device = device
        self._url_base = device._url_base
        self._control_url = service.control_url
        self._event_sub_url = service.event_sub_url

        self.actions = []
        self.action_map = {}
        self.statevars = {}
        
        SERVICE_LOGGER.debug(" service :[%s]\n" \
        " - url_base: %s\n" \
        " - SCPDURL: %s\n" \
        " - controlURL %s\n" \
        " - eventSubURL %s", 
        self.service_id, 
        self._url_base, self.scpd_url, self.control_url, self.event_sub_url)
        
        url = urljoin(self._url_base, self.scpd_url)
        SERVICE_LOGGER.debug("Reading scpd_url: %s", url)
        resp = requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            auth=self.device.http_auth,
            headers=self.device.http_headers,
        )
        resp.raise_for_status()
        actions, statevars = upnp_parser.parse_scpd_xml(str(resp.content))
        action_url = urljoin(self._url_base, self._control_url)
        self.statevars =  {item.name : item for item in statevars}
        self.action_map = {item.name : Action(self,action_url, self.service_type, item, self.statevars) for item in actions}

    def __repr__(self):
        return "<Service service_id='%s'>" % (self.service_id)

    def __getattr__(self, name):
        """
        Allow Actions to be returned as members of the Service.
        """
        try:
            return self.action_map[name]
        except KeyError:
            raise AttributeError("No attribute or action found with name %r." % name)

    def __getitem__(self, key):
        """
        Allow Actions to be returned as dictionary keys of the Service.
        """
        return self.action_map[key]

    def __dir__(self):
        """
        Add Action names to `dir(service)` output for use with tab-completion in repl.
        """
        return list(super(Service, self).__dir__()) + list(self.action_map.keys())

    @staticmethod
    def validate_subscription_response(resp):
        lc_headers = {k.lower(): v for k, v in resp.headers.items()}
        try:
            sid = lc_headers["sid"]
        except KeyError:
            raise UnexpectedResponse(
                'Event subscription call returned without a "SID" header'
            )
        try:
            timeout_str = lc_headers["timeout"].lower()
        except KeyError:
            raise UnexpectedResponse(
                'Event subscription call returned without a "Timeout" header'
            )
        if not timeout_str.startswith("second-"):
            raise UnexpectedResponse(
                "Event subscription call returned an invalid timeout value: %r"
                % timeout_str
            )
        timeout_str = timeout_str[len("Second-") :]
        try:
            timeout = None if timeout_str == "infinite" else int(timeout_str)
        except ValueError:
            raise UnexpectedResponse(
                'Event subscription call returned a timeout value which wasn\'t "infinite" or an in'
                "teger"
            )
        return sid, timeout

    @staticmethod
    def validate_subscription_renewal_response(resp):
        lc_headers = {k.lower(): v for k, v in resp.headers.items()}
        try:
            timeout_str = lc_headers["timeout"].lower()
        except KeyError:
            raise UnexpectedResponse(
                'Event subscription call returned without a "Timeout" header'
            )
        if not timeout_str.startswith("second-"):
            raise UnexpectedResponse(
                "Event subscription call returned an invalid timeout value: %r"
                % timeout_str
            )
        timeout_str = timeout_str[len("Second-") :]
        try:
            timeout = None if timeout_str == "infinite" else int(timeout_str)
        except ValueError:
            raise UnexpectedResponse(
                'Event subscription call returned a timeout value which wasn\'t "infinite" or an in'
                "teger"
            )
        return timeout

    def find_action(self, action_name): # type: ignore
        try:
            return self.action_map[action_name]
        except KeyError:
            SERVICE_LOGGER.warning('action_name[%s] not exits in find_action()', action_name)
            raise InvalidActionException('action_name', 'service中查找Action')

    def subscribe(self, callback_url, timeout=None):
        """
        Set up a subscription to the events offered by this service.
        """
        url = urljoin(self._url_base, self._event_sub_url)
        headers = dict(
            HOST=urlparse(url).netloc, CALLBACK="<%s>" % callback_url, NT="upnp:event"
        )
        if timeout is not None:
            headers["TIMEOUT"] = "Second-%s" % timeout
        resp = requests.request(
            "SUBSCRIBE", url, headers=headers, auth=self.device.http_auth
        )
        resp.raise_for_status()
        return Service.validate_subscription_response(resp)

    def renew_subscription(self, sid, timeout=None):
        """
        Renews a previously configured subscription.
        """
        url = urljoin(self._url_base, self._event_sub_url)
        headers = dict(HOST=urlparse(url).netloc, SID=sid)
        if timeout is not None:
            headers["TIMEOUT"] = "Second-%s" % timeout
        resp = requests.request(
            "SUBSCRIBE", url, headers=headers, auth=self.device.http_auth
        )
        resp.raise_for_status()
        return Service.validate_subscription_renewal_response(resp)

    def cancel_subscription(self, sid):
        """
        Unsubscribes from a previously configured subscription.
        """
        url = urljoin(self._url_base, self._event_sub_url)
        headers = dict(HOST=urlparse(url).netloc, SID=sid)
        resp = requests.request(
            "UNSUBSCRIBE", url, headers=headers, auth=self.device.http_auth
        )
        resp.raise_for_status()

class Action(upnp_parser.Action, AbstAction):
    def __init__(
        self, service, url, service_type, action:upnp_parser.Action,
        args:dict   #dict[str,upnp_parser.StateVariable]
    ):
        super().__init__(**vars(action))
        
        self.service = service
        self.url = url
        self.service_type = service_type
        self.argsdef_in:list[tuple[str, upnp_parser.StateVariable]] = []
        self.argsdef_out:list[tuple[str, upnp_parser.StateVariable]] = []
        for arg in action.arguments:
            if arg.direction.lower() == "in":
                self.argsdef_in.append((arg.name, args[arg.related_state_variable]))
            else:
                self.argsdef_out.append((arg.name, args[arg.related_state_variable]))

    def __repr__(self):
        return f"<Action {self.name!r}>"

    def __call__(self, http_auth=None, http_headers=None, **kwargs):
        arg_reasons = {}
        call_kwargs = OrderedDict()

        # Validate arguments using the SCPD stateVariable definitions
        for name, statevar in self.argsdef_in:
            if name not in kwargs:
                raise UPNPError(f"Missing required param {name!r}")
            valid, reasons = self.validate_arg(kwargs[name], statevar)
            if not valid:
                arg_reasons[name] = reasons
            # Preserve the order of call args, as listed in SCPD XML spec
            call_kwargs[name] = kwargs[name]

        if arg_reasons:
            raise ValidationError(arg_reasons)

        # Make the actual call
        ACTION_LOGGER.debug(">> %s (%s)", self.name, call_kwargs)
        soap_client = SOAP(self.url, self.service_type)

        soap_response = soap_client.call(
            self.name,
            call_kwargs,
            http_auth or self.service.device.http_auth,
            http_headers or self.service.device.http_headers,
        )
        ACTION_LOGGER.debug("<< %s (%s): %s", self.name, call_kwargs, soap_response)

        # Marshall the response to python data types
        out = {}
        for name, statevar in self.argsdef_out:
            _, value = marshal.marshal_value(statevar.data_type, soap_response[name])
            out[name] = value

        return out

    @staticmethod
    def validate_arg(arg, argdef):
        """
        Validate an incoming (unicode) string argument according the UPnP spec. Raises UPNPError.
        """
        datatype = argdef["datatype"]
        reasons = set()
        ranges = {
            "ui1": (int, 0, 255),
            "ui2": (int, 0, 65535),
            "ui4": (int, 0, 4294967295),
            "i1": (int, -128, 127),
            "i2": (int, -32768, 32767),
            "i4": (int, -2147483648, 2147483647),
            "r4": (Decimal, Decimal("3.40282347E+38"), Decimal("1.17549435E-38")),
        }
        try:
            if datatype in set(ranges.keys()):
                v_type, v_min, v_max = ranges[datatype]
                if not v_min <= v_type(arg) <= v_max:
                    reasons.add(
                        "%r datatype must be a number in the range %s to %s"
                        % (datatype, v_min, v_max)
                    )

            elif datatype in {"r8", "number", "float", "fixed.14.4"}:
                v = Decimal(arg)
                if v < 0:
                    assert (
                        Decimal("-1.79769313486232E308")
                        <= v
                        <= Decimal("4.94065645841247E-324")
                    )
                else:
                    assert (
                        Decimal("4.94065645841247E-324")
                        <= v
                        <= Decimal("1.79769313486232E308")
                    )

            elif datatype == "char":
                v = arg.decode("utf8") if isinstance(arg, bytes) else arg
                assert len(v) == 1

            elif datatype == "string":
                v = arg.decode("utf8") if isinstance(arg, bytes) else arg
                if argdef["allowed_values"] and v not in argdef["allowed_values"]:
                    reasons.add("Value %r not in allowed values list" % arg)

            elif datatype == "date":
                v = parse_date(arg)
                if any((v.hour, v.minute, v.second)):
                    reasons.add("'date' datatype must not contain a time")

            elif datatype in ("dateTime", "dateTime.tz"):
                v = parse_date(arg)
                if datatype == "dateTime" and v.tzinfo is not None:
                    reasons.add("'dateTime' datatype must not contain a timezone")

            elif datatype in ("time", "time.tz"):
                now = datetime.datetime.now(datetime.timezone.utc)
                v = parse_date(arg, default=now)
                if v.tzinfo is not None:
                    offset = v.utcoffset()
                    if offset is not None:
                        now = now + offset
                if not all((v.day == now.day, v.month == now.month, v.year == now.year)):
                    reasons.add("%r datatype must not contain a date" % datatype)
                if datatype == "time" and v.tzinfo is not None:
                    reasons.add(
                        "%r datatype must not have timezone information" % datatype
                    )

            elif datatype == "boolean":
                valid = {"true", "yes", "1", "false", "no", "0"}
                if arg.lower() not in valid:
                    reasons.add(
                        "%r datatype must be one of %s" % (datatype, ",".join(valid))
                    )

            elif datatype == "bin.base64":
                b64decode(arg)

            elif datatype == "bin.hex":
                unhexlify(arg)

            elif datatype == "uri":
                urlparse(arg)

            elif datatype == "uuid":
                if not re.match(
                    r"^[0-9a-f]{8}\-[0-9a-f]{4}\-[0-9a-f]{4}\-[0-9a-f]{4}\-[0-9a-f]{12}$",
                    arg,
                    re.I,
                ):
                    reasons.add("%r datatype must contain a valid UUID")

            else:
                reasons.add("%r datatype is unrecognised." % datatype)

        except ValueError as exc:
            reasons.add(str(exc))

        return not bool(len(reasons)), reasons
