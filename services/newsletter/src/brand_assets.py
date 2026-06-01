"""Curated public logo assets for compact circular brand marks.

The public UI uses small circular slots for publishers, LPs, and GPs. Prefer a
compact official CI or high-resolution official touch icon when available. If a
verified mark is unavailable, render a clean text fallback instead of pulling a
generic favicon service.
"""

from __future__ import annotations

import re
import ssl
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


BRAND_ASSET_CACHE: dict[str, str] = {}


BRAND_MARKS: dict[str, dict[str, str]] = {
    # News publishers
    "hankyung.com": {
        "logo_url": "https://hkstatic.hankyung.com/resource/common/img/logo/logo-hk-short-w.svg",
        "background": "#17376f",
        "border": "#17376f",
        "image_width": "30px",
        "image_height": "18px",
    },
    "marketinsight.hankyung.com": {
        "logo_url": "https://hkstatic.hankyung.com/resource/common/img/logo/logo-hk-short-w.svg",
        "background": "#17376f",
        "border": "#17376f",
        "image_width": "30px",
        "image_height": "18px",
    },
    "mk.co.kr": {
        "logo_url": "https://static.mk.co.kr/favicon_180180.png",
    },
    "dealsite.co.kr": {
        "logo_url": "https://dealsite.co.kr/static/images/favicon.svg",
    },
    "etoday.co.kr": {
        "logo_url": "https://www.etoday.co.kr/images/etoday_logo_pc.png",
        "image_width": "31px",
        "image_height": "15px",
    },
    "investchosun.com": {
        "logo_url": "https://img.investchosun.com/images/2025/logo_header.svg",
        "image_width": "32px",
        "image_height": "13px",
    },
    "thebell.co.kr": {
        "logo_url": "https://image.thebell.co.kr/thebell10/img/2020/top-logo.png",
        "image_width": "31px",
        "image_height": "17px",
    },
    "naver.com": {
        "logo_url": "https://www.naver.com/favicon.ico",
        "background": "#03c75a",
        "border": "#03c75a",
    },
    "news.google.com": {
        "logo_url": "https://www.gstatic.com/images/branding/product/2x/news_64dp.png",
    },
    "view.asiae.co.kr": {
        "logo_url": "https://cwstatic.asiae.co.kr/asiae_v2/asiae_news.png",
    },
    "sedaily.com": {
        "logo_url": "https://static.sedaily.com/img/favicon-228.png",
    },
    "biz.chosun.com": {
        "logo_url": "https://biz.chosun.com/pf/resources/icons/favicon_chosun.png?d=446",
    },
    "edaily.co.kr": {
        "logo_url": "https://image.edaily.co.kr/images/favicon/favicon_180x180.png",
    },
    "fnnews.com": {
        "logo_url": "https://static.fnnews.com/resources/w/img/icon2020/favicon-96x96.png",
    },
    "bloter.net": {
        "logo_url": "https://www.bloter.net/image/logo/snslogo_20240118025249.png",
    },
    "newstopkorea.com": {
        "logo_url": "https://cdn.newstopkorea.com/favicon.ico",
    },
    "news.einfomax.co.kr": {
        "logo_url": "https://news.einfomax.co.kr/image/logo/snslogo_20231006045256.png",
    },
    "biz.heraldcorp.com": {
        "logo_url": "https://static.heraldcorp.com/wbazic/biz/www/image/m_touch_icon180.png",
    },
    "mt.co.kr": {
        "logo_url": "https://menu.mt.co.kr/common/favicons/favicon-180.ico",
    },
    "newspim.com": {
        "logo_url": "https://img.newspim.com/m/mweb/favicon_144X144V2.png",
    },
    "kgnews.co.kr": {
        "logo_url": "https://www.kgnews.co.kr/data/skin/layout/1/m19/images/favicon144.png",
    },
    "newstomato.com": {
        "logo_url": "https://www.newstomato.com/images/logo.png",
        "image_width": "31px",
        "image_height": "11px",
    },
    "wowtv.co.kr": {
        "logo_url": "https://img.wowtv.co.kr/MobileStyle/images/common/img-header-ci01.png",
        "image_width": "31px",
        "image_height": "10px",
    },
    "joseilbo.com": {
        "logo_url": "https://m.joseilbo.com/images/jose_head_logo.png",
        "image_width": "31px",
        "image_height": "11px",
    },
    # Platform/company marks commonly surfaced in deal/news contexts.
    "thevc.kr": {
        "logo_url": "https://ui-resources.thevc.kr/cis/thevc_logo_rectangle_transparent_64.png",
        "background": "#111827",
        "border": "#111827",
        "image_width": "30px",
        "image_height": "18px",
    },
    # GP/LP directory
    "mbkpartners.com": {
        "logo_url": "https://www.mbkpartners.com/mbk/images/common/og_image.png",
        "background": "#183f7a",
        "border": "#183f7a",
    },
    "mbkpartnerslp.com": {
        "logo_url": "https://www.mbkpartners.com/mbk/images/common/og_image.png",
        "background": "#183f7a",
        "border": "#183f7a",
    },
    "hcompany.com": {
        "logo_url": "https://www.hcompany.com/assets/img/icon/favicon.png",
    },
    "immholdings.co.kr": {
        "logo_url": "https://imminvestment.com/imm/wp-content/uploads/2017/01/favicon.png",
        "background": "#6fca55",
        "border": "#6fca55",
    },
    "imminvestment.com": {
        "logo_url": "https://imminvestment.com/imm/wp-content/uploads/2017/01/favicon.png",
        "background": "#6fca55",
        "border": "#6fca55",
    },
    "kvic.or.kr": {
        "logo_url": "https://www.kvic.or.kr/resources/img/common/logo.png",
        "image_width": "31px",
        "image_height": "6px",
    },
    "fund.nps.or.kr": {
        "logo_url": "https://www.nps.or.kr/images/contents/ci_logo3.png",
        "image_width": "30px",
        "image_height": "24px",
    },
    "nps.or.kr": {
        "logo_url": "https://www.nps.or.kr/images/contents/ci_logo3.png",
        "image_width": "30px",
        "image_height": "24px",
    },
    "kdb.co.kr": {
        "logo_url": "https://www.kdb.co.kr/wcmscontents/hmp/ch/bi/bi/rc/img_symbol_chbi.png",
        "image_width": "30px",
        "image_height": "27px",
    },
    "kgrowth.or.kr": {
        "logo_url": "https://www.kgrowth.or.kr/images/logo_white.png",
        "background": "#111827",
        "border": "#111827",
        "image_width": "31px",
        "image_height": "9px",
    },
    "apfs.kr": {
        "logo_url": "https://www.apfs.kr/images/about_apfs/ci_img_2.png",
        "image_width": "30px",
        "image_height": "27px",
    },
    "koreapost.go.kr": {
        "logo_url": "https://www.koreapost.go.kr/site/kpost/images/bg/cymbol_mark.png",
        "image_width": "32px",
        "image_height": "15px",
    },
    "ktcu.or.kr": {
        "logo_url": "https://www.ktcu.or.kr/humanframe/theme/pc/assets/images/common/logo_thek.png",
        "image_width": "32px",
        "image_height": "13px",
    },
    "cu.co.kr": {
        "logo_url": "https://www.cu.co.kr/images/web/cu/layout/logo60.png",
    },
    "stic.co.kr": {
        "logo_url": "https://www.stic.co.kr/img/com/stic_logo.png",
        "image_width": "31px",
        "image_height": "16px",
    },
    "poba.or.kr": {
        "logo_url": "https://www.poba.or.kr/static/img/poba_logo.png?ver=20250422",
    },
    "pmaa.or.kr": {
        "logo_url": "https://www.pmaa.or.kr/icon.png",
    },
    "kfcc.co.kr": {
        "logo_url": "https://www.kfcc.co.kr/static/images/bi/bi_logo.png",
        "image_width": "34px",
        "image_height": "8px",
    },
    "koreaexim.go.kr": {
        "logo_url": "https://www.koreaexim.go.kr/humanframe/theme/resources/assets/img/main/spr_gnb_ci.svg",
        "cache": "true",
        "image_width": "32px",
        "image_height": "16px",
    },
    "tp.or.kr": {
        "logo_url": "https://www.tp.or.kr/asset/tp-kr/images/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "7px",
    },
    "geps.or.kr": {
        "logo_url": "https://www.geps.or.kr/humanframe/theme/geps2022/assets/images/logo.svg",
        "image_width": "32px",
        "image_height": "5px",
    },
    "mmaa.or.kr": {
        "logo_url": "https://www.mmaa.or.kr/images/common/logo.png",
        "image_width": "32px",
        "image_height": "15px",
    },
    "cw.or.kr": {
        "logo_url": "https://www.cw.or.kr/design/cwma/img/cw_logo13.png",
    },
    "kbiz.or.kr": {
        "logo_url": "https://www.kbiz.or.kr/file/resource/image/AOS_192.png",
    },
    "ibk.co.kr": {
        "logo_url": "https://www.ibk.co.kr/img/common/ic_bm_ios.png",
    },
    "dev2023.uamco.co.kr": {
        "logo_url": "https://dev2023.uamco.co.kr/assets/images/common/apple-touch-icon.png",
    },
    "skylakepe.com": {
        "logo_url": "http://www.skylakepe.com/img/logo.png",
        "cache": "true",
        "image_width": "32px",
        "image_height": "12px",
    },
    "vigpartners.com": {
        "logo_url": "https://vigpartners.com/img/p00_title.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "pe.koreainvestment.com": {
        "logo_url": "https://pe.koreainvestment.com/theme/102114/kr/assets/images/common/header-logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "macquarie.com": {
        "logo_url": "https://www.macquarie.com/assets/macq/site-wide-assets/common-icons/macquarie-logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "uckpartners.com": {
        "logo_url": "https://uckpartners.com/wp/wp-content/themes/uck/img/layout/logotype.svg",
        "image_width": "31px",
        "image_height": "5px",
    },
    "dominusinvestment.com": {
        "logo_url": "http://dominusinvestment.com/public/images/cm_logo_1.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "skspe.com": {
        "logo_url": "http://www.skspe.com/theme/basic/img/logo.png",
        "cache": "true",
        "image_width": "32px",
        "image_height": "14px",
    },
    "jklpartners.co.kr": {
        "logo_url": "https://www.jklpartners.co.kr/en/wp-content/themes/jkl_partners_eng/assets/images/img_logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "affirmacapital.com": {
        "logo_url": "https://www.affirmacapital.com/assets/img/affirma-main-logo.png",
        "image_width": "31px",
        "image_height": "10px",
    },
    "crescendoep.com": {
        "logo_url": "https://crescendoep.com/wp-content/uploads/2023/05/logo-1.png",
        "image_width": "32px",
        "image_height": "7px",
    },
    "sgpef.com": {
        "logo_url": "https://www.sgpef.com/images/common/logo.png",
        "image_width": "31px",
        "image_height": "7px",
    },
    "keistone.co.kr": {
        "logo_url": "https://keistone.co.kr/wp-content/uploads/2025/01/logotype-group.svg",
        "image_width": "32px",
        "image_height": "7px",
    },
    "enfpe.com": {
        "logo_url": "https://www.enfpe.com/img/logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "nhqv.com": {
        "logo_url": "https://www.nhsec.com/images/lay/logo.png",
        "image_width": "31px",
        "image_height": "12px",
    },
    "nhsec.com": {
        "logo_url": "https://www.nhsec.com/images/lay/logo.png",
        "image_width": "31px",
        "image_height": "12px",
    },
    "stonebridgecapital.co.kr": {
        "logo_url": "https://stonebridgecapital.co.kr/img/common/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "centroidip.com": {
        "logo_url": "https://framerusercontent.com/images/yAs4o0pQPUbUhUx48nfHFyvYik.png",
    },
    "premierpartners.co.kr": {
        "logo_url": "https://premierpartners.co.kr/wp-content/uploads/2024/11/pre_ci_003.svg",
        "image_width": "31px",
        "image_height": "8px",
    },
    "pinetreeim.com": {
        "logo_url": "http://www.pinetreeim.com/data/skin/default/images/da_image/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "sjlpartners.com": {
        "logo_url": "https://www.sjlpartners.com/resources/images/common/logo_black.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "jcpartnersonline.co.kr": {
        "logo_url": "https://jcpartnersonline.co.kr/img/top_logo.jpg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "pe.daishin.com": {
        "logo_url": "https://pe.daishin.com/group/pe/2017private/images/main/nav_logo.png",
        "image_width": "31px",
        "image_height": "11px",
    },
    "daishin.com": {
        "logo_url": "https://www.daishin.com/DW/images/common/h1_daishin.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "glenwoodpe.com": {
        "logo_url": "https://static.wixstatic.com/media/aee169_0dffaf3dc904410ebd627493c491c796~mv2.png/v1/fill/w_180,h_180,lg_1,usm_0.66_1.00_0.01/aee169_0dffaf3dc904410ebd627493c491c796~mv2.png",
    },
    "jnpef.com": {
        "logo_url": "https://www.jnpef.com/images/common/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kamco.or.kr": {
        "logo_url": "https://www.kamco.or.kr/common/img/headlogo.png",
        "image_width": "31px",
        "image_height": "7px",
    },
    "curiouspe.com": {
        "logo_url": "http://curiouspe.com/images/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kbsec.com": {
        "logo_url": "https://rc.kbsec.com/reNew/images/logo-copy.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "praxiscp.com": {
        "logo_url": "https://www.praxiscp.com/img/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "vc.miraeassetcapital.com": {
        "logo_url": "https://vc.miraeassetcapital.com/resource/mb/img/comm/og_mac.png",
    },
    "qcapital.co.kr": {
        "logo_url": "https://www.qcapital.co.kr/images/logo/main_logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "bnwinv.com": {
        "logo_url": "http://www.bnwinv.com/wordpress/wp-content/uploads/2018/01/logo_bg.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "corstonecapital.com": {
        "logo_url": "https://corstonecapital.com/wp-content/uploads/2020/05/corstonelogo-black.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kcgifund.com": {
        "logo_url": "http://www.kcgifund.com/img/common/logo.svg",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "daolpe.com": {
        "logo_url": "http://www.daolpe.com/public/favicon/favicon.ico",
        "cache": "true",
        "image_width": "24px",
        "image_height": "24px",
    },
    "wiipco.com": {
        "logo_url": "http://www.wiipco.com/kr/asset/images/common/logo_b.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "venture.miraeasset.co.kr": {
        "logo_url": "http://venture.miraeasset.co.kr/images/pc/common/Logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "nauib.com": {
        "logo_url": "https://www.nauib.com/images/common/logo2.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "yuantakorea.com": {
        "logo_url": "https://www.yuantakorea.com/images/top/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "laic.kr": {
        "logo_url": "http://www.laic.kr/img/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "sig-fund.com": {
        "logo_url": "http://sig-fund.com/public/img/logo/logox2.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "excelsiorcapitalasia.com": {
        "logo_url": "https://www.excelsiorcapitalasia.com/img/logo/logo-eca.gif",
        "image_width": "31px",
        "image_height": "13px",
    },
    "alchemistcap.com": {
        "logo_url": "https://static.wixstatic.com/media/60a6ae_60d9169353144fcfa9700e67d8c0a5cb~mv2.png/v1/fill/w_96,h_80,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/alch.png",
    },
    "stellainv.com": {
        "logo_url": "https://stellainv.com/wp-content/themes/generatepress-child/img/logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "greenharbor-pe.com": {
        "logo_url": "https://lh3.googleusercontent.com/nwelThpQMiTlidE0TBsAojEuyw2nB6r7F3Q3XkmTcnY0tzsOKddvOJBb9Qhlc1m-jG0KK7jNQV5F8vvPcWk_0mhngSJMEUZcukUxBxsDoE8iRC8QVEBpM3s=s0",
    },
    "pactumpe.com": {
        "logo_url": "https://static.wixstatic.com/media/72ad57_fee29aaa17bb445fa37bfc156daece47~mv2.png",
        "background": "#111827",
        "border": "#111827",
        "image_width": "31px",
        "image_height": "13px",
    },
    "nohnpartners.com": {
        "logo_url": "http://www.nohnpartners.com/images/header/h_logo_s.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "yuantainvest.com": {
        "logo_url": "http://yuantainvest.com/wp-content/themes/yuanta/img/logo_c.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "lxiv.kr": {
        "logo_url": "https://www.lxiv.kr/img/nav-logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "eugenepe.co.kr": {
        "logo_url": "https://www.eugenepe.co.kr/images/common/footer_logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "fund.eugenefn.com": {
        "logo_url": "http://fund.eugenefn.com/images/common_new/logo.gif",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "sclowy.com": {
        "logo_url": "https://sclowy.com/app/uploads/2025/12/sclowy-logo-black-scaled.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "highlandep.co.kr": {
        "logo_url": "http://highlandep.co.kr/img/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "forestgp.com": {
        "logo_url": "https://forestgp.com/wp-content/uploads/2018/11/regular-logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "pine-partners.store": {
        "logo_url": "https://www.pine-partners.store/logo.jpg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "idealpe.co.kr": {
        "logo_url": "https://static.wixstatic.com/media/8d1a2b_598c818f5cf840bda45c00073883f6c8~mv2.png",
    },
    "lb-pe.com": {
        "logo_url": "http://www.lb-pe.com/data/skin/default/images/main/logo_big.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "synaptic-investment.com": {
        "logo_url": "http://synaptic-investment.com/images/common/h_logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "skscredit.com": {
        "logo_url": "http://skscredit.com/theme/basic/img/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "dspe.kr": {
        "logo_url": "https://images.squarespace-cdn.com/content/v1/61385885427d7a43ba5e7a89/763b5f1e-25eb-4a0d-aa69-99caf58c9c62/DSPE+logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "am.imminvestment.com": {
        "logo_url": "https://am.imminvestment.com/ko/wp-content/themes/imm_iv/assets/images/logo.svg",
        "background": "#111827",
        "border": "#111827",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kdbinv.co.kr": {
        "logo_url": "http://www.kdbinv.co.kr/kdbinv/theme/new/_images/layout/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "investments.miraeasset.com": {
        "logo_url": "https://investments.miraeasset.com/magi/assets/images/common/logo_color.svg",
        "image_width": "31px",
        "image_height": "11px",
    },
    "kbam.co.kr": {
        "logo_url": "https://www.kbam.co.kr/static/img/common/property-img.png",
    },
    "wooripe.com": {
        "logo_url": "https://www.wooripe.com/images/common/logo_kor.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "sbva.vc": {
        "logo_url": "https://sbva.vc/assets-front/images/logo.png",
        "allow_insecure_ssl": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "paratusinvestment.com": {
        "logo_url": "https://paratusinvestment.com/img/common/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "skylakeinvestment.com": {
        "logo_url": "http://www.skylakepe.com/img/logo.png",
        "cache": "true",
        "image_width": "32px",
        "image_height": "12px",
    },
    "securities.miraeasset.com": {
        "logo_url": "https://securities.miraeasset.com/newir/publishing/pc/images/direct/img_ci_logo02_eng.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "home.imeritz.com": {
        "logo_url": "http://home.imeritz.com/include/images/comm/logo.gif",
        "cache": "true",
        "image_width": "32px",
        "image_height": "5px",
    },
    "kiwoominvest.com": {
        "logo_url": "https://www.kiwoominvest.com/images/logo-ft.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "mkif.com": {
        "logo_url": "https://www.mkif.com/assets/mkif/site-wide-assets/macquarie-logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "ktb.co.kr": {
        "logo_url": "https://www.ktb.co.kr/image/pop/h1_pe.png",
        "image_width": "31px",
        "image_height": "12px",
    },
    "shinhanfund.com": {
        "logo_url": "https://www.shinhanfund.com/static/pc/img/common/logo.svg",
        "image_width": "31px",
        "image_height": "6px",
    },
    "vlinvest.com": {
        "logo_url": "https://www.vlinvest.com/theme/business/extend/sections/header/vlinvest_header/img/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "eumpe.com": {
        "logo_url": "https://www.eumpe.com/data/common/clogo_img",
        "image_width": "31px",
        "image_height": "13px",
    },
    "eastbridge.asia": {
        "logo_url": "https://images.squarespace-cdn.com/content/5c626e1df4e5310c654345ed/1558095176492-J3FWC332TIIYOWE4CI4A/EB+LOGO.png?content-type=image%2Fpng",
        "image_width": "31px",
        "image_height": "7px",
    },
    "kipvc.com": {
        "logo_url": "https://www.kipvc.com/assets/logo_kor-DQc0PpYh.jpg",
        "allow_insecure_ssl": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hqap.com": {
        "logo_url": "https://www.hqap.com/img/headlogoen.jpg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hana-aamc.com": {
        "logo_url": "https://www.hana-aamc.com/ko/assets/images/common/share.png",
    },
    "svinvest.com": {
        "logo_url": "https://www.svinvest.com/wp-content/themes/sv/assets/images/mo-logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "ajuib.co.kr": {
        "logo_url": "https://www.ajuib.co.kr/static/images/common/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "arknpartners.com": {
        "logo_url": "https://www.arknpartners.com/static/images/logo_black.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "securities.koreainvestment.com": {
        "logo_url": "https://securities.koreainvestment.com/inc/img/gnb/logo.png",
        "image_width": "31px",
        "image_height": "6px",
    },
    "empbelstar.com": {
        "logo_url": "https://www.empbelstar.com/wp-content/themes/empbelstar/assets/images/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "sbik.co.kr": {
        "logo_url": "https://www.sbik.co.kr/common/images/common/main_logo.gif",
        "image_width": "31px",
        "image_height": "13px",
    },
    "nautic.com": {
        "logo_url": "https://nautic.com/wp-content/themes/nautic-2015/img/header_logo.png?x65017",
        "image_width": "31px",
        "image_height": "13px",
    },
    "shinyoung.com": {
        "logo_url": "https://www.shinyoung.com/favicon.png",
    },
    "shinhanvc.com": {
        "logo_url": "https://www.shinhanvc.com/images/logo_b.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "intervest.co.kr": {
        "logo_url": "https://intervest.co.kr/assets/images/thumb_img.jpg",
    },
    "kdbc.co.kr": {
        "logo_url": "https://www.kdbc.co.kr/images/h1-ci-kdb.gif",
        "image_width": "31px",
        "image_height": "13px",
    },
    "clsacapital.com": {
        "logo_url": "https://www.clsacapital.com/images/cp-logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kbic.co.kr": {
        "logo_url": "http://www.kbic.co.kr/images/icon/apple-icon-180x180.png",
        "cache": "true",
    },
    "energyipartners.com": {
        "logo_url": "http://www.energyipartners.com/images/common/h1_logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "ckdvc.co.kr": {
        "logo_url": "http://www.ckdvc.co.kr/image/logo.gif",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "nhbank.com": {
        "logo_url": "https://www.nhbank.com/KO/images/common/logo_sub.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "daoudata.co.kr": {
        "logo_url": "https://www.daoudata.co.kr/icons/group/kiwoom-private.png",
    },
    "nicefni.co.kr": {
        "logo_url": "http://www.nicefni.co.kr/images/inc/logo_240821.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "wwg.kr": {
        "logo_url": "https://wwg.kr/assets/images/common/ft_logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "mastern.co.kr": {
        "logo_url": "http://www.mastern.co.kr/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "npxcap.com": {
        "logo_url": "https://www.npxcap.com/_next/static/media/npxcap-logo.eba687ee.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "reverentpartners.com": {
        "logo_url": "https://reverentpartners.com/_nuxt/img/logo.39c032e.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kiwoom.com": {
        "logo_url": "https://www.kiwoom.com/h/kws/assets/images/common/header-logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "widuspartners.com": {
        "logo_url": "https://widuspartners.com/wp-content/themes/widus_new/assets/img/logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hassetfund.com": {
        "logo_url": "https://www.hassetfund.com/media/images/eicijasanunyong_rogo_v2.original.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "quadim.com": {
        "logo_url": "https://cdn.imweb.me/upload/S2021123174638f4a88897/979196630d05a.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "avespartners.com": {
        "logo_url": "https://www.avespartners.com/img/aves_logo_big.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "jcurveinvest.com": {
        "logo_url": "https://www.jcurveinvest.com/logo.jpg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "tinvestment.co.kr": {
        "logo_url": "http://www.tinvestment.co.kr/img/logo01.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "krossroad.co.kr": {
        "logo_url": "https://static.wixstatic.com/media/f2d9cc_dd96dfbe4caf448f984664f871b7a714~mv2.png/v1/fill/w_382,h_128,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/f2d9cc_dd96dfbe4caf448f984664f871b7a714~mv2.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "pscp.co.kr": {
        "logo_url": "https://pscp.co.kr/ko/wp-content/uploads/2024/08/CAPITAL_Logo_white.png",
        "background": "#111827",
        "border": "#111827",
        "image_width": "31px",
        "image_height": "13px",
    },
    "mainst5.com": {
        "logo_url": "https://mainst5.com/ms-logo-dark.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "dsasset.com": {
        "logo_url": "https://dsasset.com/images/common/menu-logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "smilegateinvestment.com": {
        "logo_url": "https://www.smilegateinvestment.com/ko/images/logo_w_smaill.png?v=190828",
        "background": "#111827",
        "border": "#111827",
        "image_width": "31px",
        "image_height": "13px",
    },
    "alphasset.com": {
        "logo_url": "https://alphasset.com/views/res/imgs/common/logo_img_footer.svg",
        "background": "#111827",
        "border": "#111827",
        "image_width": "31px",
        "image_height": "13px",
    },
    "i-discovery.com": {
        "logo_url": "https://www.i-discovery.com/d_html/front/images/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kiwoomam.com": {
        "logo_url": "https://www.kiwoomam.com/resources/pc/images/common/ico_comm.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "midasasset.com": {
        "logo_url": "https://midasasset.com/eng/wp-content/themes/midasasset_new_eng/images/img_logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "gravitype.com": {
        "logo_url": "http://gravitype.com/wp/wp-content/themes/gravitype/resources/images/logo.svg",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "atupartners.com": {
        "logo_url": "https://www.atupartners.com/images/common/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hanafni.com": {
        "logo_url": "http://www.hanafni.com/image/main/logo_hanafni_black.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "tchapartners.com": {
        "logo_url": "https://www.tchapartners.com/theme/tcha/img/footer-logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kclavis.com": {
        "logo_url": "http://www.kclavis.com/images/common/h_logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "eninvestment.co.kr": {
        "logo_url": "http://www.eninvestment.co.kr/images/common/foot_logo.jpg",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "metainvestment.co.kr": {
        "logo_url": "https://www.metainvestment.co.kr/main/img/company-logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "igisip.com": {
        "logo_url": "https://www.igisip.com/image/common/logo_off.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "metistone.com": {
        "logo_url": "https://www.metistone.com/storage/upload_images/yd55bEh7uHElVZOCzfRtEieqDviQEvyQVJJmjimc.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "shinhansec.com": {
        "logo_url": "https://open.shinhansec.com/new_ir/static/images/common/h1_logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "ibkc.co.kr": {
        "logo_url": "https://www.ibkc.co.kr/hom/res/img/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "utc.co.kr": {
        "logo_url": "http://www.utc.co.kr/main/image/main/logo_n.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "arges.co.kr": {
        "logo_url": "http://www.arges.co.kr/images/logo_c.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "orchestraprivateequity.com": {
        "logo_url": "https://www.orchestraprivateequity.com/images/common/img_logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "yjai.co.kr": {
        "logo_url": "http://yjai.co.kr/data/file/logo_1.gif",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "ttuprivateequity.com": {
        "logo_url": "https://cdn.imweb.me/thumbnail/20220810/e37a7e1f51732.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "crevisse.com": {
        "logo_url": "https://cdn.imweb.me/thumbnail/20190822/f3fb1e364444e.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "dreamstone-partners.com": {
        "logo_url": "https://static.wixstatic.com/media/e61e9f_94c62fbb41894b0aa7e38ec0180b4a7b~mv2.png/v1/fill/w_128,h_45,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/%EB%93%9C%EB%A6%BC%EC%8A%A4%ED%86%A42.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "fineinvestment.co.kr": {
        "logo_url": "https://fineinvestment.co.kr/media/images/fine_logo.original.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "fine-partners.co.kr": {
        "logo_url": "https://www.fine-partners.co.kr/common/img/logo_kor_black.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "s2l.co.kr": {
        "logo_url": "https://static.wixstatic.com/media/831013_96b75f41d85c4b979462941d48c923d7~mv2.jpg/v1/crop/x_233,y_855,w_541,h_164/fill/w_264,h_80,al_c,q_80,usm_0.66_1.00_0.01,enc_avif,quality_auto/%EC%97%90%EC%8A%A4%ED%88%AC%EC%97%98_%EC%88%98%EC%A0%95-01.jpg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "lakebridgeep.com": {
        "logo_url": "https://lakebridgeep.com/wp-content/uploads/2020/04/logo-wh01.svg",
        "background": "#111827",
        "border": "#111827",
        "image_width": "31px",
        "image_height": "13px",
    },
    "roipartners.co.kr": {
        "logo_url": "http://www.roipartners.co.kr/images/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "mintventures.bio": {
        "logo_url": "http://mintventures.bio/assets/images/common/logo.svg",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "lbinvestment.com": {
        "logo_url": "https://lbinvestment.com/wp-content/uploads/2024/02/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "aim-inv.com": {
        "logo_url": "http://aim-inv.com/web/images/logo_w.svg",
        "cache": "true",
        "background": "#111827",
        "border": "#111827",
        "image_width": "31px",
        "image_height": "13px",
    },
    "ibks.com": {
        "logo_url": "https://www.ibks.com/nimg/logo.gif",
        "image_width": "31px",
        "image_height": "13px",
    },
    "gsape.com": {
        "logo_url": "https://static.wixstatic.com/media/024d51_d965ad6678114be6a3272030d404c40c~mv2.png/v1/fill/w_81,h_42,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/g2110.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "onventure.co.kr": {
        "logo_url": "https://static.wixstatic.com/media/1b033a_61927d2bc1ff44199e3fd792137a9a1f~mv2.png/v1/fill/w_554,h_124,al_c,lg_1,q_85,enc_avif,quality_auto/%25EC%2598%25A4%25EC%2597%2594%2520%25EB%25B0%25B0%25EA%25B2%25BD%25EC%25A7%2580%25EC%259B%2580_edited.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "alignpartnerscap.com": {
        "logo_url": "https://alignpartnerscap.com/images/logo_footer.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "shcap.co.kr": {
        "logo_url": "https://www.shcap.co.kr/resources/img/renewal/fvc/android-icon-192x192.png",
    },
    "oraclevc.co.kr": {
        "logo_url": "https://www.oraclevc.co.kr/assets/img/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "bankerstreet.com": {
        "logo_url": "https://www.bankerstreet.com/sh_img/hd/top_menu/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kpartners.co.kr": {
        "logo_url": "http://kpartners.co.kr/wordpress/wp-content/uploads/2020/01/%EB%A1%9C%EA%B3%A0.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "bnkfn.co.kr": {
        "logo_url": "https://www.bnkfn.co.kr/img/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "openwaterinv.co.kr": {
        "logo_url": "http://openwaterinv.co.kr/off/img/logo2.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "pearlfn.com": {
        "logo_url": "https://pearlfn.com/public/img/logo/logo_c_xs.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "piainvestment.com": {
        "logo_url": "https://www.piainvestment.com/images/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hginitiative.com": {
        "logo_url": "https://www.hginitiative.com/wp-content/uploads/2022/08/cropped-HGI-%EB%A1%9C%EA%B3%A0-%EC%84%B8%EB%A1%9C%ED%98%95-square.png",
    },
    "m-vc.co.kr": {
        "logo_url": "http://www.m-vc.co.kr/uploads/logo/6a0acfb52d341.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "timefolio.co.kr": {
        "logo_url": "https://www.timefolio.co.kr/images/common/logo1.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "weventures.co.kr": {
        "logo_url": "https://cdn.imweb.me/upload/S202105189780c6de5e170/8b771026799d4.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "clobe.ai": {
        "logo_url": "https://framerusercontent.com/images/30h7Bmp6vJAuwJqyiGKlrADyTbU.png",
    },
    "sparklabs.co.kr": {
        "logo_url": "https://static.wixstatic.com/media/e7d3c7_fbb0f89e176c48b594addce332c035f6~mv2.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "koreitasset.com": {
        "logo_url": "https://www.koreitasset.com/assets/img/img-header-logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "wadizpartners.com": {
        "logo_url": "https://partners.wadiz.kr/_next/static/media/artwork-logo-wadiz-partners-black.a56291d4.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "everbestpartners.com": {
        "logo_url": "http://everbestpartners.com/public/img/logo/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "ccvc.co.kr": {
        "logo_url": "https://launchpack-storage.s3.ap-northeast-2.amazonaws.com/media/ccvc/non-path/42746849.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "credpart.com": {
        "logo_url": "http://www.credpart.com/files/attach/images/main/credianlogo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "wintergold.co.kr": {
        "logo_url": "https://cdn.imweb.me/thumbnail/20250226/8caebdaf6c51b.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "mgni.co.kr": {
        "logo_url": "https://mgni.co.kr/wp-content/uploads/2018/01/logo-b.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "v-investment.co.kr": {
        "logo_url": "https://www.v-investment.co.kr:443/theme/vtas/images/common/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "k2investment.co.kr": {
        "logo_url": "http://k2investment.co.kr/wp-content/uploads/2020/05/K2Logo_s03.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "sgivc.com": {
        "logo_url": "http://www.sgivc.com/wordpress/wp-content/uploads/2025/05/%EC%82%BC%ED%98%B8%EA%B7%B8%EB%A6%B0%EC%9D%B8%EB%B2%A0%EC%8A%A4%ED%8A%B8%EB%A8%BC%ED%8A%B8%EB%A1%9C%EA%B3%A0jpg.jpg",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kolon.com": {
        "logo_url": "https://www.kolon.com/common/kr/images/logo-landscape-screen-white.svg",
        "background": "#111827",
        "border": "#111827",
        "image_width": "31px",
        "image_height": "13px",
    },
    "newsroom.cj.net": {
        "logo_url": "https://img.newsroom.cj.net/wp-content/uploads/2022/08/CJ-Investment-Logo-1.jpg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "dayli.partners": {
        "logo_url": "https://www.dayli.partners/images/common/logo-c.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "idgcapital.co.kr": {
        "logo_url": "https://idgcapital.co.kr/sites/all/themes/idgcapital/images/logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "fwd-ep.com": {
        "logo_url": "https://fwd-ep.com/wp-content/uploads/2023/08/cropped-400JpgdpiLogoCroppedBW-150x44.jpg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "mapleinvest.co.kr": {
        "logo_url": "http://www.mapleinvest.co.kr/theme/theme021/img/comm/logo2.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "ascentpe.co.kr": {
        "logo_url": "https://ascentpe.co.kr/wp-content/uploads/2022/02/ascent-logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "bookook.co.kr": {
        "logo_url": "http://www.bookook.co.kr/resources/img/h1_logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "golfzoncounty.com": {
        "logo_url": "https://www.golfzoncounty.com/assets/images/img_logo_01.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "capefn.com": {
        "logo_url": "https://www.capefn.com/images/web/util/title/logoCape.gif",
        "image_width": "31px",
        "image_height": "13px",
    },
    "lnsvc.co.kr": {
        "logo_url": "http://www.lnsvc.co.kr/image/main/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "leading.co.kr": {
        "logo_url": "http://www.leading.co.kr/img/common/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hankookcapital.co.kr": {
        "logo_url": "https://www.hankookcapital.co.kr/res/hkc/images/common/img_logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "seoulip.com": {
        "logo_url": "http://www.seoulip.com/data/skin/respon_default/images/skin/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "woorifni.co.kr": {
        "logo_url": "https://www.woorifni.co.kr/img/main/info_logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "primer.kr": {
        "logo_url": "https://upload.cafenono.com/image/logo/20250528/154454_usvLjARwfjOwKixwz1?q=80&s=720x1",
        "image_width": "31px",
        "image_height": "13px",
    },
    "krypton36.co": {
        "logo_url": "http://krypton36.co/wp-content/uploads/2018/10/krt-logo-e1541144644219.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "bluepoint.ac": {
        "logo_url": "https://blue-storage.s3.ap-northeast-2.amazonaws.com/og_image.png",
    },
    "sticventures.co.kr": {
        "logo_url": "https://www.sticventures.co.kr/kor/img/com/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "pulsarcapm.com": {
        "logo_url": "https://images.squarespace-cdn.com/content/v1/5adc3976f407b40b053dc06e/a8c21873-3bfd-432b-ae05-ebede8838ac2/2.png?format=1500w",
        "image_width": "31px",
        "image_height": "13px",
    },
    "quintessa.kr": {
        "logo_url": "https://quintessa.kr/image/logo.gif",
        "image_width": "31px",
        "image_height": "13px",
    },
    "vogo.co.kr": {
        "logo_url": "https://cdn.imweb.me/upload/S202206238c1faf53170cd/27b84bdbe5738.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "company.daishin.com": {
        "logo_url": "https://company.daishin.com/group/images/group/sub/ci_simg2.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "acuoncapital.com": {
        "logo_url": "https://www.acuoncapital.com/assets/images/common/header_logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "brainib.com": {
        "logo_url": "http://www.brainib.com/images/share/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "poscoinvestment.com": {
        "logo_url": "https://www.poscoinvestment.com/resources/assets/images/logo_footer_black.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "consus.co.kr": {
        "logo_url": "https://www.consus.co.kr/static_source/images/pc/header/logo-ci.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "base.investments": {
        "logo_url": "https://base.investments/favicon/apple-touch-icon.png",
    },
    "iprovest.com": {
        "logo_url": "https://www.iprovest.com/images/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "sbinvestment.co.kr": {
        "logo_url": "http://sbinvestment.co.kr/images/sb_logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "rohatyngroup.com": {
        "logo_url": "https://cdn.prod.website-files.com/6566440b0341f5e373911789/6566440b0341f5e3739117a7_logo-dark.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "sc.com": {
        "logo_url": "https://av.sc.com/assets/global/images/components/header/standard-chartered-logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hqkorea.com": {
        "logo_url": "https://cdn.prod.website-files.com/6582759176a3fe2c441c2755/6582759176a3fe2c441c27cd_company-subpage-logo.webp",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hanwhafund.co.kr": {
        "logo_url": "https://www.hanwhafund.co.kr/assets/images/common/logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "vogo-fund.com": {
        "logo_url": "https://www.vogo-fund.com/img/common/m_logo_ov.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "jarvisam.com": {
        "logo_url": "https://www.jarvisam.com/media/images/jabiseu_rogo2.original.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "dscinvestment.com": {
        "logo_url": "http://www.dscinvestment.com/images/footer_logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hnckpartners.com": {
        "logo_url": "http://www.hnckpartners.com/img/logo-symbol.png",
        "cache": "true",
    },
    "platformasset.com": {
        "logo_url": "http://www.platformasset.com/images/common/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kninvest.co.kr": {
        "logo_url": "http://www.kninvest.co.kr/images/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "piadvisor.com": {
        "logo_url": "http://piadvisor.com/images/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "esinvestor.com": {
        "logo_url": "https://www.esinvestor.com/assets/images/main/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "qedeqy.com": {
        "logo_url": "https://www.qedeqy.com/file/197237588",
        "image_width": "31px",
        "image_height": "13px",
    },
    "daolfund.com": {
        "logo_url": "https://www.daolfund.com/static/pc/images/common/logo_header_b.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "npinvestment.co.kr": {
        "logo_url": "https://npinvestment.co.kr/wp-content/uploads/2026/04/np-logo-white-1.png",
        "background": "#111827",
        "border": "#111827",
    },
    "axisinvestment.co.kr": {
        "logo_url": "http://www.axisinvestment.co.kr/web/service/project/axis/Data/img/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "orioncm.co.kr": {
        "logo_url": "https://www.orioncm.co.kr/media/images/oraieonjasanunyong_rogo.original.png",
        "image_width": "31px",
        "image_height": "17px",
    },
    "jbam.co.kr": {
        "logo_url": "http://www.jbam.co.kr/images/front/kr/layout/logo_s.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "15px",
    },
    "woorivp.com": {
        "logo_url": "https://www.woorivp.com/static/home/en/images/common/logo_footer.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "wadiz.kr": {
        "logo_url": "https://static.wadiz.kr/assets/icon/apple-touch-icon-180x180.png",
    },
    "lski.co.kr": {
        "logo_url": "http://www.lski.co.kr/img/logo_on.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "17px",
    },
    "uoninvestment.com": {
        "logo_url": "http://www.uoninvestment.com/static/img/jm_logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "smsino.co.kr": {
        "logo_url": "https://www.smsino.co.kr/images/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hanwhainvestment.com": {
        "logo_url": "https://hanwhainvestment.com/theme/hanwhainvestment/img/logo-color.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "encompany.co.kr": {
        "logo_url": "http://encompany.co.kr/images/encompany_logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "translink.kr": {
        "logo_url": "https://translink.kr/images/Logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "sks.co.kr": {
        "logo_url": "https://www.sks.co.kr/main/common/img/common/logo.png",
        "image_width": "31px",
        "image_height": "10px",
    },
    "sol.co.kr": {
        "logo_url": "http://www.sol.co.kr/img/SOL_logo.gif",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "dominusinvestment.com": {
        "logo_url": "http://www.dominusinvestment.com/public/images/cm_logo_1.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "imfnsec.com": {
        "logo_url": "https://www.imfnsec.com/images/main/2017/logo_2024CI_iMsec.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "gntechvc.co.kr": {
        "logo_url": "https://www.gntechvc.co.kr/uploads/media/logo_color.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "trustonasset.com": {
        "logo_url": "https://www.trustonasset.com/wp-content/themes/TRUSTON-2025/images/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "aioninvestment.com": {
        "logo_url": "https://www.aioninvestment.com/media/images/aion_logo.original.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "eigpartners.com": {
        "logo_url": "https://eigpartners.com/wp-content/themes/eigpartners/assets/images/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "skenergy.com": {
        "logo_url": "https://www.skenergy.com/resources/images/company/ci_logo_mark-01.jpg",
    },
    "nhn.com": {
        "logo_url": "https://www.nhn.com/NHN.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "dbsec.co.kr": {
        "logo_url": "https://www.dbsec.co.kr/img/dbsec_800x400.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "home.barclays": {
        "logo_url": "https://home.barclays/content/dam/home-barclays/images/generic/barclays-eagle.svg",
    },
    "blackstone.com": {
        "logo_url": "https://www.blackstone.com/wp-content/uploads/sites/2/2020/07/Blackstone-PRESS-QUALITY-6312.png",
    },
    "beyondmusic.io": {
        "logo_url": "https://beyondmusic.io/wp-content/uploads/2025/04/cropped-%ED%8C%8C%EB%B9%84%EC%BD%98-192x192.png",
    },
    "balbeckpl.com": {
        "logo_url": "https://balbeckpl.com/media/images/bikeipieljasanunyong_rogo.original.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "behighvc.co.kr": {
        "logo_url": "https://static.wixstatic.com/media/489bde_a042f3ac48d0462aa1ad4df2653bdff3~mv2.jpg/v1/fill/w_192,h_192,lg_1,usm_0.66_1.00_0.01/489bde_a042f3ac48d0462aa1ad4df2653bdff3~mv2.jpg",
    },
    "semainv.com": {
        "logo_url": "https://semainv.com/image/logo_1.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "songhyuninvestment.co.kr": {
        "logo_url": "https://www.songhyuninvestment.co.kr/resource/images/logo/logo-brand.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "stonebridge.co.kr": {
        "logo_url": "https://stonebridge.co.kr/img/common/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "acurusgroup.com": {
        "logo_url": "http://acurusgroup.com/logo.png",
        "cache": "true",
    },
    "arakref.co.kr": {
        "logo_url": "https://arakref.co.kr/media/images/ARAkoria_rogo.original.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "mdmam.com": {
        "logo_url": "https://www.mdmam.com/img/common/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "mgcap.co.kr": {
        "logo_url": "https://mgcap.co.kr/assets/images/com/svg/topLogo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "eospartners.com": {
        "logo_url": "https://eospartners.com/wp-content/uploads/2025/05/LOGO.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "invictusasia.com": {
        "logo_url": "https://invictusasia.com/images/logo.png",
        "allow_insecure_ssl": "true",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "capitaland.com": {
        "logo_url": "https://www.capitaland.com/etc.clientlibs/capitaland/clientlibs/clientlib-capitaland/resources/icon-192x192.png",
    },
    "cspartners.co.kr": {
        "logo_url": "https://cspartners.co.kr/uploads/media/2023/10/SVG.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kiwoomcapital.com": {
        "logo_url": "https://www.kiwoomcapital.com/img/common/kw_logo_sub.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "tsinvestment.co.kr": {
        "logo_url": "https://www.tsinvestment.co.kr/logo.jpg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "harborbricks.co.kr": {
        "logo_url": "https://harborbricks.co.kr/img/common/logo.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "acelp.co.kr": {
        "logo_url": "https://www.acelp.co.kr/superboard/data/siteconfig/2021041419394616183967867220.png",
        "image_width": "31px",
        "image_height": "13px",
    },
    "klnpartnerslp.com": {
        "logo_url": "https://klnpartnerslp.com/img/svg/img_logo.svg",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "paramark.vc": {
        "logo_url": "https://assets.softr-files.com/applications/17df479b-f891-4de1-9a2f-60e115e6725f/assets/13556b08-16a2-44cd-a551-372027550b46.png?rnd=1670832473516",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "ldpartners.co.kr": {
        "logo_url": "https://ldpartners.co.kr/images/main/main-logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "stassetsinv.com": {
        "logo_url": "https://lh3.googleusercontent.com/sitesv/AA5AbUD-kj41LfdJfP_sv3vZQFqnQMGe9EZ6AJP4UPSu2m8_NeKoFhW8YA-jnYGoz9YXNFRAM1Ko3UkH7nWlq-GDv6XJph0hVE-ucgKcy9_ypyIYjhPbYXyQTk3voOcgvcxwIwnxAQKr6-DDsjtFizZpfgiEk6ohbNw33H7CH-cI4C7BpJRrV2ztNKNHU5n6OV7bFkQcHA=w1280",
        "cache": "true",
    },
    "goldenoak.co.kr": {
        "logo_url": "https://www.goldenoak.co.kr/public/img/logo/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "paxtone.com": {
        "logo_url": "https://www.paxtone.com/images/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "rylsonpe.com": {
        "logo_url": "https://rylsonpe.com/favicon.png",
        "cache": "true",
    },
    "hanandbrothers.biz": {
        "logo_url": "https://static.wixstatic.com/media/f88915_8e0bbdd9e4be4296a88bfed3887eb65a~mv2.png/v1/fill/w_310,h_78,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/%EB%A1%9C%EA%B3%A0111.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "investwells.com": {
        "logo_url": "https://www.investwells.com/img/logo-b.svg",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "stonebridgeventures.vc": {
        "logo_url": "https://www.stonebridgeventures.vc/static/img/favicon.ico",
        "cache": "true",
    },
    "orix.co.jp": {
        "logo_url": "https://www.orix.co.jp/ORIX_favicon_152x152.png",
        "cache": "true",
    },
    "rhinos.kr": {
        "logo_url": "https://static.wixstatic.com/media/54b59d_f18d4f00075642d89c49be8688789d20~mv2.png/v1/fill/w_175,h_60,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/54b59d_f18d4f00075642d89c49be8688789d20~mv2.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "hyundai-invest.com": {
        "logo_url": "https://hyundai-invest.com/homepage/images/common/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "gcinvestment.co.kr": {
        "logo_url": "https://lh3.googleusercontent.com/ZV_wA3zVWCjdnS98KL6-TIvN0DZQbXc1jY7D8l3DWv46137-cfCq6kgEFEFDe4zXpB7HoJ20NrDChKM8TVCW6is8aOVtWWOdATLHqAXuEl4Y4tqn6G99UA=s0",
        "cache": "true",
    },
    "hanaw.com": {
        "logo_url": "https://www.hanaw.com/common/img/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "unisoncap.com": {
        "logo_url": "https://www.unisoncap.com/apple-touch-icon.png",
        "cache": "true",
    },
    "stellainv.com": {
        "logo_url": "https://stellainv.com/wp-content/themes/generatepress-child/img/logo.svg",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "sprottkorea.co.kr": {
        "logo_url": "https://lh3.googleusercontent.com/nwelThpQMiTlidE0TBsAojEuyw2nB6r7F3Q3XkmTcnY0tzsOKddvOJBb9Qhlc1m-jG0KK7jNQV5F8vvPcWk_0mhngSJMEUZcukUxBxsDoE8iRC8QVEBpM3s=s0",
        "cache": "true",
    },
    "simonefg.co.kr": {
        "logo_url": "https://simonefg.co.kr/theme/basic/img/ci.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "7tep.com": {
        "logo_url": "http://www.7tep.com/kor/images/common/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
}


PUBLISHER_DOMAINS: dict[str, str] = {
    "한국경제": "hankyung.com",
    "매일경제": "mk.co.kr",
    "딜사이트": "dealsite.co.kr",
    "더벨": "thebell.co.kr",
    "인베스트조선": "investchosun.com",
    "이투데이": "etoday.co.kr",
    "조선비즈": "biz.chosun.com",
    "아시아경제": "view.asiae.co.kr",
    "서울경제": "sedaily.com",
    "이데일리": "edaily.co.kr",
    "연합인포맥스": "news.einfomax.co.kr",
    "뉴스톱": "newstopkorea.com",
    "블로터": "bloter.net",
    "헤럴드경제": "biz.heraldcorp.com",
    "머니투데이": "mt.co.kr",
    "파이낸셜뉴스": "fnnews.com",
    "뉴스토마토": "newstomato.com",
    "한국경제TV": "wowtv.co.kr",
    "뉴스핌": "newspim.com",
    "조세일보": "joseilbo.com",
    "경기신문": "kgnews.co.kr",
    "구글뉴스": "news.google.com",
    "Google News": "news.google.com",
}


BRAND_LABEL_DOMAINS: dict[str, str] = {
    "브이엘인베스트먼트": "vlinvest.com",
    "이음프라이빗에쿼티": "eumpe.com",
    "이스트브릿지파트너스": "eastbridge.asia",
    "한국투자파트너스": "kipvc.com",
    "에이치앤큐에쿼티파트너스": "hqap.com",
    "하나대체투자자산운용": "hana-aamc.com",
    "에스브이인베스트먼트": "svinvest.com",
    "아주아이비투자": "ajuib.co.kr",
    "아크앤파트너스": "arknpartners.com",
    "한국투자증권": "securities.koreainvestment.com",
    "이엠피벨스타": "empbelstar.com",
    "에스비아이인베스트먼트": "sbik.co.kr",
    "노틱인베스트먼트": "nautic.com",
    "신영증권": "shinyoung.com",
    "신한벤처투자": "shinhanvc.com",
    "인터베스트": "intervest.co.kr",
    "산은캐피탈": "kdbc.co.kr",
    "씨엘에스에이캐피탈파트너스코리아": "clsacapital.com",
    "케이비인베스트먼트": "kbic.co.kr",
    "키스톤프라이빗에쿼티": "keistone.co.kr",
    "비엔더블유인베스트먼트": "bnwinv.com",
    "코스톤아시아": "corstonecapital.com",
    "케이씨지아이": "kcgifund.com",
    "다올프라이빗에쿼티": "daolpe.com",
    "원익투자파트너스": "wiipco.com",
    "미래에셋벤처투자": "venture.miraeasset.co.kr",
    "나우아이비캐피탈": "nauib.com",
    "유안타증권": "yuantakorea.com",
    "린드먼아시아인베스트먼트": "laic.kr",
    "삼천리자산운용": "sig-fund.com",
    "엑셀시아캐피탈코리아": "excelsiorcapitalasia.com",
    "어펄마캐피탈크레딧솔루션즈코리아": "affirmacapital.com",
    "알케미스트캐피탈파트너스코리아": "alchemistcap.com",
    "스텔라인베스트먼트": "stellainv.com",
    "그린하버": "greenharbor-pe.com",
    "팩텀프라이빗에쿼티": "pactumpe.com",
    "노앤파트너스": "nohnpartners.com",
    "유안타인베스트먼트": "yuantainvest.com",
    "제이케이엘크레딧인베스트먼트": "jklpartners.co.kr",
    "엘엑스인베스트먼트": "lxiv.kr",
    "유진프라이빗에쿼티": "eugenepe.co.kr",
    "유진자산운용": "fund.eugenefn.com",
    "에스씨로이코리아": "sclowy.com",
    "하일랜드에쿼티파트너스": "highlandep.co.kr",
    "포레스트파트너스": "forestgp.com",
    "파인트리파트너스": "pine-partners.store",
    "이상파트너스": "idealpe.co.kr",
    "엘비프라이빗에쿼티": "lb-pe.com",
    "시냅틱인베스트먼트": "synaptic-investment.com",
    "에스케이에스크레딧": "skscredit.com",
    "디에스프라이빗에쿼티": "dspe.kr",
    "아이엠엠자산운용": "am.imminvestment.com",
    "이아이피자산운용": "energyipartners.com",
    "씨케이디창업투자": "ckdvc.co.kr",
    "농협은행": "nhbank.com",
    "키움프라이빗에쿼티": "daoudata.co.kr",
    "나이스투자파트너스": "nicefni.co.kr",
    "더블유더블유지자산운용": "wwg.kr",
    "마스턴파트너스": "mastern.co.kr",
    "엔피엑스프라이빗에쿼티": "npxcap.com",
    "레버런트파트너스": "reverentpartners.com",
    "키움증권": "kiwoom.com",
    "위더스파트너스코리아지피": "widuspartners.com",
    "에이치자산운용": "hassetfund.com",
    "쿼드자산운용": "quadim.com",
    "에이비즈파트너스": "avespartners.com",
    "제이커브인베스트먼트": "jcurveinvest.com",
    "티인베스트먼트": "tinvestment.co.kr",
    "크로스로드파트너스": "krossroad.co.kr",
    "피에스캐피탈파트너스": "pscp.co.kr",
    "스틱얼터너티브자산운용": "stic.co.kr",
    "메인스트리트인베스트먼트": "mainst5.com",
    "디에스자산운용": "dsasset.com",
    "스마일게이트인베스트먼트": "smilegateinvestment.com",
    "알파자산운용": "alphasset.com",
    "인텔렉추얼디스커버리": "i-discovery.com",
    "키움투자자산운용": "kiwoomam.com",
    "마이다스프라이빗에쿼티": "midasasset.com",
    "그래비티프라이빗에쿼티": "gravitype.com",
    "에이티유파트너스": "atupartners.com",
    "하나에프앤아이": "hanafni.com",
    "미래에셋증권": "securities.miraeasset.com",
    "차파트너스자산운용": "tchapartners.com",
    "케이클라비스": "kclavis.com",
    "이앤인베스트먼트": "eninvestment.co.kr",
    "메타인베스트먼트": "metainvestment.co.kr",
    "이지스투자파트너스": "igisip.com",
    "메티스톤에퀴티파트너스": "metistone.com",
    "신한투자증권": "shinhansec.com",
    "아이비케이캐피탈": "ibkc.co.kr",
    "유티씨인베스트먼트": "utc.co.kr",
    "아르게스프라이빗에쿼티": "arges.co.kr",
    "오케스트라어드바이저스코리아": "orchestraprivateequity.com",
    "와이제이에이인베스트먼트": "yjai.co.kr",
    "티티유프라이빗에쿼티": "ttuprivateequity.com",
    "크레비스파트너스": "crevisse.com",
    "드림스톤프라이빗에쿼티": "dreamstone-partners.com",
    "화인자산운용": "fineinvestment.co.kr",
    "에스투엘파트너스": "s2l.co.kr",
    "레이크브릿지에쿼티파트너스": "lakebridgeep.com",
    "로이투자파트너스": "roipartners.co.kr",
    "민트벤처파트너스": "mintventures.bio",
    "신한자산운용": "shinhanfund.com",
    "엘비인베스트먼트": "lbinvestment.com",
    "에임인베스트먼트": "aim-inv.com",
    "아이비케이투자증권": "ibks.com",
    "지에스에이프라이빗에쿼티": "gsape.com",
    "오엔벤처투자": "onventure.co.kr",
    "얼라인파트너스자산운용": "alignpartnerscap.com",
    "신한캐피탈": "shcap.co.kr",
    "오라클벤처투자": "oraclevc.co.kr",
    "뱅커스트릿": "bankerstreet.com",
    "컴퍼니케이파트너스": "kpartners.co.kr",
    "비엔케이투자증권": "bnkfn.co.kr",
    "오픈워터인베스트먼트": "openwaterinv.co.kr",
    "펄인베스트먼트": "pearlfn.com",
    "피아이에이인베스트먼트파트너스": "piainvestment.com",
    "에이치지이니셔티브": "hginitiative.com",
    "엠벤처투자": "m-vc.co.kr",
    "타임폴리오자산운용": "timefolio.co.kr",
    "위벤처스": "weventures.co.kr",
    "브이원씨": "clobe.ai",
    "스파크랩파트너스": "sparklabs.co.kr",
    "코레이트자산운용": "koreitasset.com",
    "와디즈파트너스": "wadizpartners.com",
    "에버베스트파트너스": "everbestpartners.com",
    "쿨리지코너인베스트먼트": "ccvc.co.kr",
    "크레디언파트너스": "credpart.com",
    "윈터골드": "wintergold.co.kr",
    "마그나인베스트먼트": "mgni.co.kr",
    "브이인베스트먼트": "v-investment.co.kr",
    "케이투자파트너스": "k2investment.co.kr",
    "삼호그린인베스트먼트": "sgivc.com",
    "코오롱인베스트먼트": "kolon.com",
    "타임와이즈인베스트먼트": "newsroom.cj.net",
    "씨제이인베스트먼트": "newsroom.cj.net",
    "CJ인베스트먼트": "newsroom.cj.net",
    "데일리파트너스": "dayli.partners",
    "아이디지캐피탈파트너스코리아": "idgcapital.co.kr",
    "포워드에퀴티파트너스": "fwd-ep.com",
    "메이플투자파트너스": "mapleinvest.co.kr",
    "에이씨피씨피이": "ascentpe.co.kr",
    "부국증권": "bookook.co.kr",
    "골프존카운티": "golfzoncounty.com",
    "케이프투자증권": "capefn.com",
    "엘앤에스벤처캐피탈": "lnsvc.co.kr",
    "리딩투자증권": "leading.co.kr",
    "한국캐피탈": "hankookcapital.co.kr",
    "서울투자파트너스": "seoulip.com",
    "우리금융에프앤아이": "woorifni.co.kr",
    "프라이머시즌5": "primer.kr",
    "크립톤": "krypton36.co",
    "블루포인트파트너스": "bluepoint.ac",
    "스틱벤처스": "sticventures.co.kr",
    "펄사캐피탈매니지먼트": "pulsarcapm.com",
    "퀸테사인베스트먼트": "quintessa.kr",
    "맥쿼리코리아오퍼튜니티즈운용": "macquarie.com",
    "브이아이지파트너스이호": "vigpartners.com",
    "신한대체투자운용": "shinhanfund.com",
    "하나금융투자": "hanaw.com",
    "유니슨캐피탈코리아": "unisoncap.com",
    "미래에셋대우": "securities.miraeasset.com",
    "보고인베스트먼트그룹": "vogo.co.kr",
    "대신증권": "company.daishin.com",
    "애큐온캐피탈": "acuoncapital.com",
    "케이비증권": "kbsec.com",
    "KB증권": "kbsec.com",
    "브레인자산운용": "brainib.com",
    "포스코기술투자": "poscoinvestment.com",
    "칸서스자산운용": "consus.co.kr",
    "베이스인베스트먼트": "base.investments",
    "교보증권": "iprovest.com",
    "SBI인베스트먼트": "sbik.co.kr",
    "로하틴그룹코리아": "rohatyngroup.com",
    "스탠다드차타드프라이빗에쿼티매니져스코리아": "sc.com",
    "엔에이치투자증권": "nhsec.com",
    "NH투자증권": "nhsec.com",
    "신한금융투자": "shinhansec.com",
    "에이치앤큐코리아파트너스": "hqkorea.com",
    "한화자산운용": "hanwhafund.co.kr",
    "보고인베스트먼트": "vigpartners.com",
    "보고펀드자산운용": "vogo-fund.com",
    "대우증권": "securities.miraeasset.com",
    "네오플럭스": "shinhanvc.com",
    "자비스인베스트먼트": "jarvisam.com",
    "자비스자산운용": "jarvisam.com",
    "디에스씨인베스트먼트": "dscinvestment.com",
    "에이치앤씨케이파트너스": "hnckpartners.com",
    "플랫폼파트너스자산운용": "platformasset.com",
    "케이앤투자파트너스": "kninvest.co.kr",
    "피아이에이자산운용": "piadvisor.com",
    "이에스인베스터": "esinvestor.com",
    "노틱캐피탈코리아": "qedeqy.com",
    "KTB자산운용": "daolfund.com",
    "케이티비자산운용": "daolfund.com",
    "다올자산운용": "daolfund.com",
    "엔피인베스트먼트": "npinvestment.co.kr",
    "액시스인베스트먼트": "axisinvestment.co.kr",
    "오라이언자산운용": "orioncm.co.kr",
    "제이비자산운용": "jbam.co.kr",
    "우리벤처파트너스": "woorivp.com",
    "위벤처스(유)": "weventures.co.kr",
    "와디즈플랫폼": "wadiz.kr",
    "엘에스케이인베스트먼트": "lski.co.kr",
    "유온인베스트먼트": "uoninvestment.com",
    "에스엠시노기술투자": "smsino.co.kr",
    "한화인베스트먼트": "hanwhainvestment.com",
    "이앤컴퍼니": "encompany.co.kr",
    "케이티비네트워크": "woorivp.com",
    "KTB네트워크": "woorivp.com",
    "차파트너스": "tchapartners.com",
    "에스케이증권": "sks.co.kr",
    "트랜스링크인베스트먼트": "translink.kr",
    "솔인베스트": "sol.co.kr",
    "도미누스에쿼티파트너스": "dominusinvestment.com",
    "하이투자증권": "imfnsec.com",
    "지앤텍벤처투자": "gntechvc.co.kr",
    "트러스톤자산운용": "trustonasset.com",
    "아이온자산운용": "aioninvestment.com",
    "EIG글로벌에너지코리아": "eigpartners.com",
    "이아이지글로벌에너지코리아": "eigpartners.com",
    "NHN인베스트먼트": "nhn.com",
    "엔에이치엔인베스트먼트": "nhn.com",
    "SK에너지": "skenergy.com",
    "에스케이에너지": "skenergy.com",
    "동부증권": "dbsec.co.kr",
    "디비금융투자": "dbsec.co.kr",
    "바클레이즈코리아지피": "home.barclays",
    "블랙스톤코리아어드바이저스": "blackstone.com",
    "비욘드뮤직파트너스": "beyondmusic.io",
    "비케이피엘자산운용": "balbeckpl.com",
    "비하이인베스트먼트": "behighvc.co.kr",
    "세마인베스트먼트": "semainv.com",
    "송현인베스트먼트": "songhyuninvestment.co.kr",
    "스톤브릿지홀딩스": "stonebridge.co.kr",
    "어큐러스그룹": "acurusgroup.com",
    "에이알에이코리아자산운용": "arakref.co.kr",
    "엠디엠자산운용": "mdmam.com",
    "엠캐피탈": "mgcap.co.kr",
    "이오스파트너즈": "eospartners.com",
    "인빅터스프라이빗에쿼티아시아": "invictusasia.com",
    "캐피탈랜드투자운용": "capitaland.com",
    "캡스톤파트너스": "cspartners.co.kr",
    "키움캐피탈": "kiwoomcapital.com",
    "티에스인베스트먼트": "tsinvestment.co.kr",
    "하버브릭스파트너스": "harborbricks.co.kr",
    "에이스에쿼티파트너스": "acelp.co.kr",
    "케이엘앤파트너스": "klnpartnerslp.com",
    "파라마크벤처스": "paramark.vc",
    "라데팡스파트너스": "ldpartners.co.kr",
    "어센트프라이빗에쿼티": "ascentpe.co.kr",
    "스타셋인베스트먼트": "stassetsinv.com",
    "골든오크인베스트먼트": "goldenoak.co.kr",
    "팍스톤매니지먼트": "paxtone.com",
    "릴슨프라이빗에쿼티": "rylsonpe.com",
    "한앤브라더스": "hanandbrothers.biz",
    "더웰스인베스트먼트": "investwells.com",
    "스톤브릿지벤처스": "stonebridgeventures.vc",
    "오릭스프라이빗에쿼티코리아": "orix.co.jp",
    "라이노스자산운용": "rhinos.kr",
    "현대투자파트너스": "hyundai-invest.com",
    "게임체인저인베스트먼트": "gcinvestment.co.kr",
    "하나증권": "hanaw.com",
    "하나금융투자": "hanaw.com",
    "유니슨캐피탈코리아": "unisoncap.com",
    "KTB투자증권": "ktb.co.kr",
    "에이치앤큐아시아퍼시픽코리아": "hqap.com",
    "스텔라에쿼티파트너스": "stellainv.com",
    "스프랏코리아": "sprottkorea.co.kr",
    "시몬느자산운용": "simonefg.co.kr",
    "메이플인베스트먼트": "mapleinvest.co.kr",
    "나이스에프앤아이": "nicefni.co.kr",
    "디스커버리인베스트먼트": "i-discovery.com",
    "아스테란인베스트먼트": "avespartners.com",
    "세븐트리에쿼티파트너스": "7tep.com",
    "화인파트너스": "fine-partners.co.kr",
    "화인투자파트너스": "fineinvestment.co.kr",
}


def normalized_domain(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    domain = (parsed.hostname or raw).lower().strip()
    return domain.removeprefix("www.")


def domain_from_url(url: object) -> str:
    return normalized_domain(url)


def publisher_domain(label: object) -> str:
    normalized = str(label or "").strip()
    return PUBLISHER_DOMAINS.get(normalized, "") or BRAND_LABEL_DOMAINS.get(normalized, "")


def brand_key_for_domain(domain: object) -> str:
    normalized = normalized_domain(domain)
    if not normalized:
        return ""
    for suffix in sorted(BRAND_MARKS, key=len, reverse=True):
        if normalized == suffix or normalized.endswith(f".{suffix}"):
            return suffix
    return ""


def preferred_domain(url: object, label: object = "") -> str:
    domain = normalized_domain(url)
    label_domain = publisher_domain(label)
    if label_domain and (not domain or domain == "news.google.com"):
        return label_domain
    return domain or label_domain


def _asset_extension(logo_url: str, content_type: str) -> str:
    suffix = Path(urlparse(logo_url).path).suffix.lower()
    if suffix in {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".avif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    content_type = content_type.lower()
    if "svg" in content_type:
        return ".svg"
    if "png" in content_type:
        return ".png"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "webp" in content_type:
        return ".webp"
    if "avif" in content_type:
        return ".avif"
    if "icon" in content_type or "ico" in content_type:
        return ".ico"
    return ".img"


def _brand_asset_filename(key: str, logo_url: str, content_type: str) -> str:
    safe_key = re.sub(r"[^A-Za-z0-9]+", "-", key).strip("-").lower() or "brand"
    return f"{safe_key}{_asset_extension(logo_url, content_type)}"


def prepare_brand_asset_cache(output_dir: Path, asset_prefix: str = "assets/brand-marks") -> None:
    """Cache selected official marks into the generated site.

    A few official GP logos are still served over HTTP only. GitHub Pages is
    HTTPS, so those images need a local copy to avoid mixed-content blocking.
    The cache is best-effort: if a remote source is unavailable, rendering
    falls back to the remote HTTPS URL or to a text slot when only HTTP exists.
    """

    BRAND_ASSET_CACHE.clear()
    asset_dir = output_dir / asset_prefix
    asset_dir.mkdir(parents=True, exist_ok=True)
    for key, mark in BRAND_MARKS.items():
        logo_url = mark.get("logo_url", "")
        if not logo_url:
            continue
        should_cache = not logo_url.startswith("data:") and "google.com/s2/favicons" not in logo_url
        if not should_cache:
            continue
        try:
            request = Request(
                logo_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                },
            )
            try:
                with urlopen(request, timeout=10) as response:
                    content_type = response.headers.get("content-type", "")
                    payload = response.read(1_500_000)
                    final_url = response.geturl()
            except Exception:
                if mark.get("allow_insecure_ssl") != "true":
                    raise
                with urlopen(request, timeout=10, context=ssl._create_unverified_context()) as response:
                    content_type = response.headers.get("content-type", "")
                    payload = response.read(1_500_000)
                    final_url = response.geturl()
            if not payload or "text/html" in content_type.lower():
                continue
        except Exception:
            continue
        filename = _brand_asset_filename(key, final_url or logo_url, content_type)
        (asset_dir / filename).write_bytes(payload)
        BRAND_ASSET_CACHE[key] = f"{asset_prefix}/{filename}"


def brand_logo_url(url: object, label: object = "") -> str:
    domain = preferred_domain(url, label)
    key = brand_key_for_domain(domain)
    if key:
        cached_url = BRAND_ASSET_CACHE.get(key, "")
        if cached_url:
            return cached_url
        logo_url = BRAND_MARKS[key].get("logo_url", "")
        if logo_url:
            if BRAND_MARKS[key].get("cache") == "true":
                return ""
            if logo_url.startswith("http://"):
                return ""
            return logo_url
    return ""


def brand_style_string(url: object = "", label: object = "") -> str:
    domain = preferred_domain(url, label)
    key = brand_key_for_domain(domain)
    if not key:
        return ""
    mark = BRAND_MARKS[key]
    background = mark.get("background", "")
    border = mark.get("border", background)
    parts = []
    if background:
        parts.append(f"--logo-bg: {background};")
    if border:
        parts.append(f"--logo-border: {border};")
    image_width = mark.get("image_width", "")
    image_height = mark.get("image_height", "")
    if image_width:
        parts.append(f"--logo-img-width: {image_width};")
    if image_height:
        parts.append(f"--logo-img-height: {image_height};")
    return " ".join(parts)


def brand_style_attr(url: object = "", label: object = "") -> str:
    style = brand_style_string(url, label)
    return f' style="{style}"' if style else ""
