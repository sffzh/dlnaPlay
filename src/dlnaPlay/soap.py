## this module is copied from [flyte/upnpclient]

import re
import requests
import xml.etree.ElementTree as ET
from dlnaPlay._logger import get_logger

SOAP_TIMEOUT = 30
NS_SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
NS_UPNP_ERR = "urn:schemas-upnp-org:control-1-0"
ENCODING_STYLE = "http://schemas.xmlsoap.org/soap/encoding/"
ENCODING = "utf-8"

logger = get_logger("SOAP")

class SOAPError(Exception):
    pass

class SOAPProtocolError(Exception):
    pass

class SOAP:
    """Simple SOAP client for UPnP control."""

    def __init__(self, url, service_type):
        self.url = url
        self.service_type = service_type
        self._host = self.url.split("//", 1)[1].split("/", 1)[0]

    # -----------------------------
    # 工具函数
    # -----------------------------
    @staticmethod
    def _remove_extraneous_xml_declarations(xml_str):
        """移除多余的 XML 声明"""
        xml_declaration = ""
        if xml_str.startswith("<?xml"):
            xml_declaration, xml_str = xml_str.split("?>", maxsplit=1)
            xml_declaration += "?>"
        xml_str = re.sub(r"<\?xml.*?\?>", "", xml_str, flags=re.I)
        return xml_declaration + xml_str

    def _extract_upnperror(self, err_xml):
        """
        从 UPnP 错误响应中提取 errorCode 和 errorDescription。
        """
        ns = {"s": NS_SOAP_ENV}

        fault_str = err_xml.findtext(".//s:Fault/faultstring", namespaces=ns)
        if not fault_str:
            raise SOAPProtocolError("Fault string not found in UPnP error response")

        # detail 下的错误节点名称与 faultstring 相同
        detail_path = f".//s:Fault/detail/{fault_str}"
        err_node = err_xml.find(detail_path, ns)
        if err_node is None:
            raise SOAPProtocolError(f"Error detail node '{fault_str}' not found")

        err_code = err_node.findtext("errorCode")
        err_desc = err_node.findtext("errorDescription")

        if err_code is None or err_desc is None:
            raise SOAPProtocolError("Missing errorCode or errorDescription")

        return int(err_code), err_desc

    # -----------------------------
    # 主调用函数
    # -----------------------------
    def call(self, action_name, arg_in=None, http_auth=None, http_headers=None):
        if arg_in is None:
            arg_in = {}

        # -----------------------------
        # 构造 SOAP 请求 XML
        # -----------------------------
        soap_env = f"{{{NS_SOAP_ENV}}}"
        m = f"{{{self.service_type}}}"

        envelope = ET.Element(soap_env + "Envelope")
        envelope.set(soap_env + "encodingStyle", ENCODING_STYLE)

        body = ET.SubElement(envelope, soap_env + "Body")
        action = ET.SubElement(body, m + action_name)

        for key, value in arg_in.items():
            child = ET.SubElement(action, key)
            child.text = str(value)

        xml_body = ET.tostring(envelope, encoding=ENCODING, xml_declaration=True)

        headers = {
            "SOAPAction": f'"{self.service_type}#{action_name}"',
            "Host": self._host,
            "Content-Type": "text/xml",
            "Content-Length": str(len(xml_body)),
        }
        headers.update(http_headers or {})

        # -----------------------------
        # 发送 HTTP 请求
        # -----------------------------
        try:
            resp = requests.post(
                self.url, xml_body, headers=headers,
                timeout=SOAP_TIMEOUT, auth=http_auth
            )
            resp.raise_for_status()

        except requests.exceptions.HTTPError as exc:
            # 尝试解析 UPnP 错误
            try:
                err_xml = ET.fromstring(exc.response.content)
            except ET.ParseError:
                raise exc
            raise SOAPError(*self._extract_upnperror(err_xml))

        # -----------------------------
        # 解析响应 XML
        # -----------------------------
        xml_str = resp.content.strip()

        try:
            xml = ET.fromstring(xml_str)
        except ET.ParseError:
            xml = ET.fromstring(self._remove_extraneous_xml_declarations(xml_str))

        # 查找响应节点
        response_tag = f".//{{{self.service_type}}}{action_name}Response"
        response = xml.find(response_tag)

        if response is None:
            raise SOAPProtocolError(
                f"Response element '{action_name}Response' not found in namespace {self.service_type}"
            )

        # -----------------------------
        # 解析返回参数
        # -----------------------------
        ret = {}
        for arg in list(response):
            # 如果子节点本身包含 XML（设备未使用 CDATA）
            if list(arg):
                ret[arg.tag] = b"".join(
                    ET.tostring(child) for child in list(arg)
                )
            else:
                ret[arg.tag] = arg.text

        return ret
