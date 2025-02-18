"""
See COPYRIGHT.md for copyright information.
"""
from __future__ import annotations

import binascii
import os
from typing import Any, Optional, Union
from urllib.parse import unquote

from lxml.etree import XML, XMLSyntaxError
from lxml.etree import _Element

from arelle.ModelObjectFactory import parser
from arelle.ModelXbrl import ModelXbrl
from arelle.UrlUtil import decodeBase64DataImage, scheme
from arelle.ValidateFilingText import parseImageDataURL, validateGraphicHeaderType
from arelle.ValidateXbrl import ValidateXbrl
from arelle.typing import TypeGetText
from ..Const import supportedImgTypes

_: TypeGetText  # Handle gettext


# check image contents against mime/file ext and for Steganography
def validateImage(
    baseUrl: Optional[str],
    image: str,
    modelXbrl: ModelXbrl,
    val: ValidateXbrl,
    elt: _Element,
    evaluatedMsg: str,
    contentOtherThanXHTMLGuidance: str,
) -> None:
    """
    image: either an url or base64 in data:image style
    """
    minExternalRessourceSize = val.authParam["minExternalResourceSizekB"]
    if minExternalRessourceSize != -1:
        # transform kb to b
        minExternalRessourceSize = minExternalRessourceSize * 1024
    if scheme(image) in ("http", "https", "ftp"):
        modelXbrl.error("ESEF.4.1.6.xHTMLDocumentContainsExternalReferences" if val.unconsolidated
                        else "ESEF.3.5.1.inlineXbrlDocumentContainsExternalReferences",
                        _("Inline XBRL instance documents MUST NOT contain any reference pointing to resources outside the reporting package: %(element)s"),
                        modelObject=elt, element=elt.tag, evaluatedMsg=evaluatedMsg,
                        messageCodes=("ESEF.3.5.1.inlineXbrlDocumentContainsExternalReferences",
                                      "ESEF.4.1.6.xHTMLDocumentContainsExternalReferences"))
    elif image.startswith("data:image"):
        dataURLParts = parseImageDataURL(image)
        if not dataURLParts or not dataURLParts.isBase64:
            modelXbrl.warning(f"{contentOtherThanXHTMLGuidance}.embeddedImageNotUsingBase64Encoding",
                              _("Images included in the XHTML document SHOULD be base64 encoded: %(src)s."),
                              modelObject=elt, src=image[:128], evaluatedMsg=evaluatedMsg)
            if dataURLParts and dataURLParts.mimeSubtype and dataURLParts.data:
                checkImageContents(None, modelXbrl, elt, dataURLParts.mimeSubtype, False, unquote(dataURLParts.data), val.consolidated, val)
        else:
            if not dataURLParts.mimeSubtype:
                modelXbrl.error(f"{contentOtherThanXHTMLGuidance}.MIMETypeNotSpecified",
                                _("Images included in the XHTML document MUST be saved with MIME type specifying PNG, GIF, SVG or JPG/JPEG formats: %(src)s."),
                                modelObject=elt, src=image[:128], evaluatedMsg=evaluatedMsg)
            elif dataURLParts.mimeSubtype not in ("gif", "jpeg", "png", "svg+xml"):
                modelXbrl.error(f"{contentOtherThanXHTMLGuidance}.imageFormatNotSupported",
                                _("Images included in the XHTML document MUST be saved in PNG, GIF, SVG or JPG/JPEG formats: %(src)s."),
                                modelObject=elt, src=image[:128], evaluatedMsg=evaluatedMsg)
            # check for malicious image contents
            try:  # allow embedded newlines
                imgContents:Union[bytes, Any, str] = decodeBase64DataImage(dataURLParts.data)
                checkImageContents(None, modelXbrl, elt, str(dataURLParts.mimeSubtype), False, imgContents, val.consolidated, val)
                imgContents = b""  # deref, may be very large

            except binascii.Error as err:
                modelXbrl.error(f"{contentOtherThanXHTMLGuidance}.embeddedImageNotUsingBase64Encoding",
                                _("Base64 encoding error %(err)s in image source: %(src)s."),
                                modelObject=elt, err=str(err), src=image[:128], evaluatedMsg=evaluatedMsg)
    else:
        # presume it to be an image file, check image contents
        try:
            base = baseUrl
            normalizedUri = modelXbrl.modelManager.cntlr.webCache.normalizeUrl(image, base)
            if not modelXbrl.fileSource.isInArchive(normalizedUri):
                normalizedUri = modelXbrl.modelManager.cntlr.webCache.getfilename(normalizedUri)
            imglen = 0
            with modelXbrl.fileSource.file(normalizedUri, binary=True)[0] as fh:
                imgContents = fh.read()
                imglen += len(imgContents or '')
                checkImageContents(normalizedUri, modelXbrl, elt, os.path.splitext(image)[1], True, imgContents,
                                   val.consolidated, val)
                imgContents = b""  # deref, may be very large
            if imglen < minExternalRessourceSize:
                modelXbrl.warning(
                    "%s.imageIncludedAndNotEmbeddedAsBase64EncodedString" % contentOtherThanXHTMLGuidance,
                    _("Images SHOULD be included in the XHTML document as a base64 encoded string unless their size exceeds the minimum size for the authority (%(maxImageSize)s): %(file)s."),
                    modelObject=elt, maxImageSize=minExternalRessourceSize, file=os.path.basename(normalizedUri), evaluatedMsg=evaluatedMsg)
        except IOError as err:
            modelXbrl.error(f"{contentOtherThanXHTMLGuidance}.imageFileCannotBeLoaded",
                            _("Error opening the file '%(src)s': %(error)s"),
                            modelObject=elt, src=image, error=err, evaluatedMsg=evaluatedMsg)


def checkImageContents(
    baseURI: Optional[str],
    modelXbrl: ModelXbrl,
    imgElt: _Element,
    imgType: str,
    isFile: bool,
    data: Union[bytes, Any, str],
    consolidated: bool,
    val: ValidateXbrl,
) -> None:
    guidance = 'ESEF.2.5.1' if consolidated else 'ESEF.4.1.3'
    if "svg" in imgType:
        try:
            checkSVGContent(baseURI, modelXbrl, imgElt, data, guidance, val)
        except XMLSyntaxError as err:
            try:
                checkSVGContent(baseURI, modelXbrl, imgElt, unquote(data), guidance, val)  # Try with utf-8 decoded data as in conformance suite G4-1-3_2/TC2
            except XMLSyntaxError:
                modelXbrl.error(f"{guidance}.imageFileCannotBeLoaded",
                                _("Image SVG has XML error %(error)s"),
                                modelObject=imgElt, error=err)
        except UnicodeDecodeError as err:
            modelXbrl.error(f"{guidance}.imageFileCannotBeLoaded",
                _("Image SVG has XML error %(error)s"),
                modelObject=imgElt, error=err)
    else:
        headerType = validateGraphicHeaderType(data)  # type: ignore[arg-type]
        if (("gif" not in imgType and headerType == "gif") or
            ("jpeg" not in imgType and "jpg" not in imgType and headerType == "jpg") or
            ("png" not in imgType and headerType == "png")):
            imageDoesNotMatchItsFileExtension = f"{guidance}.imageDoesNotMatchItsFileExtension"
            incorrectMIMETypeSpecified = f"{guidance}.incorrectMIMETypeSpecified"
            if isFile:
                code = imageDoesNotMatchItsFileExtension
                message = _("File type %(headerType)s inferred from file signature does not match the file extension %(imgType)s")
            else:
                code = incorrectMIMETypeSpecified
                message = _("File type %(headerType)s inferred from file signature does not match the data URL media subtype (MIME subtype) %(imgType)s")
            modelXbrl.error(code, message,
                modelObject=imgElt, imgType=imgType, headerType=headerType,
                messageCodes=(imageDoesNotMatchItsFileExtension, incorrectMIMETypeSpecified))
        elif not any(it in imgType for it in supportedImgTypes[isFile]):
            modelXbrl.error(f"{guidance}.imageFormatNotSupported",
                            _("Images included in the XHTML document MUST be saved in PNG, GIF, SVG or JPEG formats: %(imgType)s is not supported"),
                            modelObject=imgElt, imgType=imgType)


def checkSVGContent(
    baseURI: Optional[str],
    modelXbrl: ModelXbrl,
    imgElt: _Element,
    data: Union[bytes, Any, str],
    guidance: str,
    val: ValidateXbrl,
) -> None:
    _parser, _ignored, _ignored = parser(modelXbrl, baseURI)
    elt = XML(data, parser=_parser)
    checkSVGContentElt(elt, baseURI, modelXbrl, imgElt, guidance, val)


def getHref(elt:_Element) -> str:
    simple_href = elt.get("href", "").strip()
    if len(simple_href) > 0:
        return simple_href
    else:
        # 'xlink:href' is deprecated but still used by some SVG generators
        return elt.get("{http://www.w3.org/1999/xlink}href", "").strip()


def checkSVGContentElt(
    elt: _Element,
    baseUrl: Optional[str],
    modelXbrl: ModelXbrl,
    imgElt: _Element,
    guidance: str,
    val: ValidateXbrl,
) -> None:
    rootElement = True
    for elt in elt.iter():
        if rootElement:
            if elt.tag != "{http://www.w3.org/2000/svg}svg":
                modelXbrl.error(f"{guidance}.imageFileCannotBeLoaded",
                                _("Image SVG has root element which is not svg"),
                                modelObject=imgElt)
            rootElement = False
        eltTag = elt.tag.rpartition("}")[2] # strip namespace
        if eltTag == "image":
            validateImage(baseUrl, getHref(elt), modelXbrl, val, elt, "", guidance)
        if eltTag in ("object", "script", "audio", "foreignObject", "iframe", "image", "use", "video"):
            href = elt.get("href","")
            if eltTag in ("object", "script") or "javascript:" in href:
                modelXbrl.error(f"{guidance}.executableCodePresent",
                                _("Inline XBRL images MUST NOT contain executable code: %(element)s"),
                                modelObject=imgElt, element=eltTag)
            elif scheme(href) in ("http", "https", "ftp"):
                modelXbrl.error(f"{guidance}.referencesPointingOutsideOfTheReportingPackagePresent",
                                _("Inline XBRL instance document [image] MUST NOT contain any reference pointing to resources outside the reporting package: %(element)s"),
                                modelObject=imgElt, element=eltTag)
