"""Curated public logo assets for compact circular brand marks.

The public UI uses small circular slots for publishers, LPs, and GPs. Prefer a
compact official CI or high-resolution official touch icon when available, then
fall back to Google S2 favicons only for broad coverage.
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
        "logo_url": "https://thevc.kr/favicon.ico",
        "background": "#111827",
        "border": "#111827",
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
        "logo_url": "https://www.hcompany.com/favicon.ico",
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
        "logo_url": "https://www.kvic.or.kr/resources/favicon/apple-touch-icon.png",
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
        "logo_url": "https://www.kgrowth.or.kr/favicon.ico",
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
        "logo_url": "https://www.ktcu.or.kr/humanframe/theme/pc/assets/images/common/favicon.ico",
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
        "image_width": "32px",
        "image_height": "16px",
    },
    "tp.or.kr": {
        "logo_url": "https://www.tp.or.kr/asset/tp-kr/images/favicon.ico",
    },
    "geps.or.kr": {
        "logo_url": "https://www.geps.or.kr/humanframe/theme/geps2022/assets/images/favicon.svg",
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
        "logo_url": "https://vigpartners.com/img/favicon.ico",
    },
    "pe.koreainvestment.com": {
        "logo_url": "https://securities.koreainvestment.com/favicon.ico",
    },
    "macquarie.com": {
        "logo_url": "https://www.macquarie.com/assets/macq/site-wide-assets/common-icons/macquarie-logo.svg",
        "image_width": "31px",
        "image_height": "13px",
    },
    "uckpartners.com": {
        "logo_url": "https://uckpartners.com/wp/wp-content/themes/uck/img/favicons/apple-icon-76x76.png",
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
        "logo_url": "https://affirmacapital.com/assets/img/favicon.jpg",
    },
    "crescendoep.com": {
        "logo_url": "https://crescendoep.com/wp-content/uploads/fbrfg/apple-touch-icon.png",
    },
    "sgpef.com": {
        "logo_url": "https://www.sgpef.com/images/favicon/apple-icon-76x76.png",
    },
    "keistone.co.kr": {
        "logo_url": "https://keistone.co.kr/wp-content/themes/keistone/images/favicon.png",
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
        "logo_url": "https://premierpartners.co.kr/wp-content/uploads/2024/11/favicon_002-300x300.png",
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
        "logo_url": "https://www.kamco.or.kr/common/img/common/favicon2-128.ico",
    },
    "curiouspe.com": {
        "logo_url": "http://curiouspe.com/images/logo.png",
        "cache": "true",
        "image_width": "31px",
        "image_height": "13px",
    },
    "kbsec.com": {
        "logo_url": "https://www.kbsec.com/favicon.ico",
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
        "logo_url": "https://img.securities.miraeasset.com/new2016/layout/favicon.ico",
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
        "logo_url": "https://img.securities.miraeasset.com/new2016/layout/favicon.ico",
    },
    "home.imeritz.com": {
        "logo_url": "https://home.imeritz.com/favicon.ico",
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
        "logo_url": "https://www.shinhanfund.com/static/pc/img/common/favicon.ico",
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
        "logo_url": "https://images.squarespace-cdn.com/content/5c626e1df4e5310c654345ed/1558281378541-ZDTLAPM08AM8GGUO76B6/favicon2.png?format=100w&content-type=image%2Fpng",
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
        "logo_url": "https://securities.koreainvestment.com/favicon.ico",
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


def google_favicon_url(domain: object) -> str:
    normalized = normalized_domain(domain)
    if not normalized:
        return ""
    return f"https://www.google.com/s2/favicons?domain={normalized}&sz=64"


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
    falls back to the remote HTTPS URL or to the generic favicon path.
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
            if logo_url.startswith("http://"):
                return google_favicon_url(domain)
            return logo_url
    return google_favicon_url(domain)


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
