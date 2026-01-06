import xml.etree.ElementTree as ET
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class UPnPService:
    service_type: str
    service_id: str
    scpd_url: str
    control_url: str
    event_sub_url: str

    @property
    def name(self):
        try:
            return self.service_id[self.service_id.rindex(":") + 1 :]
        except ValueError:
            return self.service_id

@dataclass
class UPnPDevice:
    device_type: str
    friendly_name: Optional[str]
    manufacturer: Optional[str]
    manufacturer_url: Optional[str]
    model_description: Optional[str]
    model_name: Optional[str]
    model_number: Optional[str]
    model_url: Optional[str]
    udn: Optional[str]
    url_base: Optional[str]
    services: List[UPnPService]
    serial_number: Optional[str]


def _get_namespace(tag: str) -> str:
    """从根节点 tag 中提取默认命名空间"""
    m = re.match(r"\{(.*)\}", tag)
    return m.group(1) if m else ""

# 解析 Device / Service
def parse_upnp_device_description(xml_text: str) -> UPnPDevice:
    root = ET.fromstring(xml_text.strip())

    # 处理默认命名空间
    ns_uri = _get_namespace(root.tag)
    ns = {"u": ns_uri} if ns_uri else {}

    def find_text(path: str) -> Optional[str]:
        elem = root.find(path, ns)
        return elem.text.strip() if elem is not None and elem.text is not None else None

    # device 节点
    device = root.find("u:device", ns)
    if device is None:
        raise ValueError("No <device> element found in UPnP description")

    def d_find_text(path: str) -> Optional[str]:
        elem = device.find(path, ns)
        return elem.text.strip() if elem is not None and elem.text is not None else None

    # 基本设备信息
    device_type = d_find_text("u:deviceType") or ""
    friendly_name = d_find_text("u:friendlyName")
    manufacturer = d_find_text("u:manufacturer")
    manufacturer_url = d_find_text("u:manufacturerURL")
    model_description = d_find_text("u:modelDescription")
    model_name = d_find_text("u:modelName")
    model_number = d_find_text("u:modelNumber")
    model_url = d_find_text("u:modelURL")
    udn = d_find_text("u:UDN")
    serial_number = d_find_text("u:serialNumber")

    # URLBase（有些设备没有）
    url_base = find_text("u:URLBase")

    # 解析 serviceList
    services: List[UPnPService] = []
    service_list = device.find("u:serviceList", ns)
    if service_list is not None:
        for s in service_list.findall("u:service", ns):
            service_type = s.findtext("u:serviceType", default="", namespaces=ns).strip()
            service_id = s.findtext("u:serviceId", default="", namespaces=ns).strip()
            scpd_url = s.findtext("u:SCPDURL", default="", namespaces=ns).strip()
            control_url = s.findtext("u:controlURL", default="", namespaces=ns).strip()
            event_sub_url = s.findtext("u:eventSubURL", default="", namespaces=ns).strip()

            services.append(
                UPnPService(
                    service_type=service_type,
                    service_id=service_id,
                    scpd_url=scpd_url,
                    control_url=control_url,
                    event_sub_url=event_sub_url,
                )
            )

    return UPnPDevice(
        device_type=device_type,
        friendly_name=friendly_name,
        manufacturer=manufacturer,
        manufacturer_url=manufacturer_url,
        model_description=model_description,
        model_name=model_name,
        model_number=model_number,
        model_url=model_url,
        udn=udn,
        url_base=url_base,
        services=services,
        serial_number=serial_number
    )


# -----------------------------
# 数据结构定义
# -----------------------------
@dataclass
class Argument:
    name: str
    direction: str
    related_state_variable: str


@dataclass
class Action:
    name: str
    arguments: List[Argument]


@dataclass
class StateVariable:
    name: str
    data_type: str
    allowed_values: Optional[set]
    send_events: bool

# ele 类型为:ET.Element
def _ele_to_str(ele, default:str = ""):
    return ele.text.strip() if ele and ele.text else default

# -----------------------------
# 主解析函数
# -----------------------------
def parse_scpd_xml(xml_text: str):
    root = ET.fromstring(xml_text)

    # 处理命名空间
    ns_uri = _get_namespace(root.tag)
    ns = {"u": ns_uri}

    # -----------------------------
    # 解析 actionList
    # -----------------------------
    actions: List[Action] = []

    action_list = root.find("u:actionList", ns)
    if action_list is not None:
        for action_node in action_list.findall("u:action", ns):
            name = _ele_to_str(action_node.find("u:name", ns))

            # 解析 argumentList
            arguments = []
            arg_list = action_node.find("u:argumentList", ns)
            if arg_list is not None:
                for arg in arg_list.findall("u:argument", ns):
                    arg_name = _ele_to_str(arg.find("u:name", ns))
                    direction = _ele_to_str(arg.find("u:direction", ns))
                    related = _ele_to_str(arg.find("u:relatedStateVariable", ns))

                    arguments.append(Argument(
                        name=arg_name,
                        direction=direction,
                        related_state_variable=related
                    ))

            actions.append(Action(name=name, arguments=arguments))

    # -----------------------------
    # 解析 serviceStateTable
    # -----------------------------
    state_variables: List[StateVariable] = []

    state_table = root.find("u:serviceStateTable", ns)
    if state_table is not None:
        for sv in state_table.findall("u:stateVariable", ns):
            name = _ele_to_str(sv.find("u:name", ns))
            data_type = _ele_to_str(sv.find("u:dataType", ns))

            # allowedValueList（可选）
            allowed_values = set()
            av_list = sv.find("u:allowedValueList", ns)
            if av_list is not None:
                for av in av_list.findall("u:allowedValue", ns):
                    allowed_values.add(_ele_to_str(av))

            send_events = sv.get("sendEvents", "yes").lower() == "yes"

            state_variables.append(StateVariable(
                name=name,
                data_type=data_type,
                allowed_values=allowed_values if allowed_values else None,
                send_events = send_events
            ))

    return actions, state_variables
