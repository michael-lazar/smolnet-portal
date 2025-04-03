from geminiportal.protocols.base import BaseRequest
from geminiportal.protocols.finger import FingerRequest
from geminiportal.protocols.gemini import GeminiRequest
from geminiportal.protocols.gopher import GopherRequest
from geminiportal.protocols.nex import NexRequest
from geminiportal.protocols.scroll import ScrollRequest
from geminiportal.protocols.spartan import SpartanRequest
from geminiportal.protocols.text import TxtRequest
from geminiportal.urls import URLReference
from geminiportal.utils import ProxyOptions


def build_proxy_request(url: URLReference, options: ProxyOptions | None = None) -> BaseRequest:
    request_class: type[BaseRequest]

    if options is None:
        options = ProxyOptions()

    if url.scheme == "spartan":
        request_class = SpartanRequest
    elif url.scheme == "text":
        request_class = TxtRequest
    elif url.scheme == "finger":
        request_class = FingerRequest
    elif url.scheme == "gemini":
        request_class = GeminiRequest
    elif url.scheme == "nex":
        request_class = NexRequest
    elif url.scheme == "gopher":
        request_class = GopherRequest
    elif url.scheme == "gophers":
        request_class = GopherRequest
    elif url.scheme == "scroll":
        request_class = ScrollRequest
    else:
        raise ValueError(f"Unsupported URL scheme: {url.scheme}")

    return request_class(url, options)
