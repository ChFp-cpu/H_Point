"""Shared browser-native theme. A palette change never rebuilds application state."""

SYSTEM_THEME_META = '<meta name="theme-color" content="#f4f8f6" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#0e1511" media="(prefers-color-scheme: dark)">'

SYSTEM_THEME_CSS = r'''
:root {
  color-scheme: light;
  --hp-background:#f4f8f6; --hp-surface:#ffffff; --hp-surface-secondary:#eef5f0;
  --hp-text-primary:#15231d; --hp-text-secondary:#53665c; --hp-border:#c5d3cb;
  --hp-accent:#b8f36b; --hp-accent-contrast:#14220e; --hp-accent-text:#2b6515;
  --hp-hover:#e5f4dd; --hp-focus:#35751c; --hp-disabled:#6b7c71;
  --hp-success:#21622d; --hp-warning:#795408; --hp-danger:#a52d36;
  --hp-input:#ffffff; --hp-popover:#ffffff; --hp-overlay:rgba(15,28,21,.58);
  --hp-chart:#398b38; --hp-map:#e7efe8; --hp-header:rgba(255,255,255,.94);
  --hp-glow:rgba(181,243,165,.25); --hp-shadow:0 8px 28px rgba(30,62,43,.055);
}
@media(prefers-color-scheme:dark) {
  :root {
    color-scheme:dark;
    --hp-background:#0e1511; --hp-surface:#171f19; --hp-surface-secondary:#202b22;
    --hp-text-primary:#edf4eb; --hp-text-secondary:#b1bfb2; --hp-border:#485b4b;
    --hp-accent:#b8f36b; --hp-accent-contrast:#14220e; --hp-accent-text:#b8f36b;
    --hp-hover:#293c23; --hp-focus:#b8f36b; --hp-disabled:#95a697;
    --hp-success:#a5e9a7; --hp-warning:#f5d47c; --hp-danger:#ffb1ad;
    --hp-input:#111912; --hp-popover:#19241b; --hp-overlay:rgba(4,9,6,.8);
    --hp-chart:#b8f36b; --hp-map:#1b2b20; --hp-header:rgba(14,21,17,.94);
    --hp-glow:rgba(43,98,70,.24); --hp-shadow:0 8px 28px rgba(0,0,0,.16);
  }
}
html:root {
  --hp-ink:var(--hp-text-primary); --hp-muted:var(--hp-text-secondary);
  --hp-line:var(--hp-border); --hp-green:var(--hp-accent-text); --hp-green-strong:var(--hp-accent-text);
  --hp-shadow-soft:var(--hp-shadow);
  --canvas:var(--hp-background); --surface:var(--hp-surface); --surface2:var(--hp-surface-secondary);
  --text:var(--hp-text-primary); --ink:var(--hp-text-primary); --muted:var(--hp-text-secondary);
  --line:var(--hp-border); --green:var(--hp-accent-text); --danger:var(--hp-danger); --shadow:var(--hp-shadow);
  background:var(--hp-background);
}
body {background:radial-gradient(ellipse at 82% 6%,var(--hp-glow),transparent 44%),var(--hp-background);color:var(--hp-text-primary)}
* {scrollbar-color:var(--hp-border) var(--hp-background)}
button,input,select,textarea {font-family:inherit}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible {outline:2px solid var(--hp-focus);outline-offset:3px}
button:disabled {color:var(--hp-disabled);cursor:default}
'''

APP_THEME_CSS = r'''
body{font-family:Manrope,Arial,sans-serif}.muted{color:var(--hp-text-secondary)}
.landingHero{overflow:clip}.landingCta{background:var(--hp-surface);border-color:var(--hp-border)}
.nav{background:var(--hp-header);border-color:var(--hp-border)}
.app,.section{background:transparent}
.workspaceCard,.workspaceMetric,.workspaceRequest,.workspaceProduct,.workspaceWalletAmount,
.workspaceChatButton,.workspaceBalance,.card,.request,.box,.identityCard,.adminWorkspace,
.adminCard,.adminMetric,.trackingCard,.eventCard,.emailVerificationCard,.contactVerification,
.landingMetric,.safetyCard,.stepCard{background:var(--hp-surface);border-color:var(--hp-border);color:var(--hp-text-primary);box-shadow:var(--hp-shadow)}
.workspaceChatButton:hover,.workspaceBalance:hover,.light:hover{background:var(--hp-hover);border-color:var(--hp-accent-text)}
.workspaceCommunityNav{display:flex;gap:8px;flex-wrap:wrap;padding:20px 0 0}.workspaceCommunityNav button{border:1px solid var(--hp-border);border-radius:12px;padding:10px 13px;background:var(--hp-surface);color:var(--hp-text-primary);font:700 12px Manrope,Arial,sans-serif;cursor:pointer}.workspaceCommunityNav button:hover{background:var(--hp-hover);border-color:var(--hp-accent-text)}
#workspaceCommunitySlot>.panel{display:block!important;padding:24px 0 0!important}.leagueBoard,.leagueCategories,.leagueStat,.duoChampionCard,.leagueRow,.eventCard,.eventEmpty,.activityStat,.progressMetric{background:var(--hp-surface)!important;border-color:var(--hp-border)!important;color:var(--hp-text-primary)}.leagueHeading h2,.leagueHero h3,.leagueSectionHead h3,.leagueStat b,.duoChampionName,.leagueMemberName,.eventCopy h3{color:var(--hp-text-primary)}.leagueHero{background:linear-gradient(135deg,var(--hp-hover),var(--hp-surface));border-color:var(--hp-border)}.leagueHeading p,.leagueHero p,.leagueProgressTop,.leagueStat span,.duoChampionMeta,.leagueMemberMeta,.eventMeta,.eventDescription,.eventCapacity{color:var(--hp-text-secondary)}.leagueLaunchNote,.leagueEmpty{background:var(--hp-surface-secondary);border-color:var(--hp-border);color:var(--hp-text-secondary)}.leagueLaunchNote b,.leagueLaunchNote span,.duoLaunchLabel{color:var(--hp-accent-text)}
.workspaceCard a{color:var(--hp-accent-text)}.workspaceCard a.btn.grad{color:var(--hp-accent-contrast)}
.showcaseKicker,.leagueEyebrow{color:var(--hp-accent-text)}
.workspacePhoto{margin:0 0 18px;overflow:hidden;border-radius:15px;background:var(--hp-surface-secondary)}.workspacePhoto img{display:block;width:100%;height:170px;object-fit:cover}.workspacePhoto figcaption{padding:8px 11px;color:var(--hp-text-secondary);font-size:10px}.workspacePhoto figcaption a{color:inherit}.communityPhotoStory{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px;margin-bottom:20px;padding:20px;border:1px solid var(--hp-border);border-radius:20px;background:linear-gradient(135deg,var(--hp-hover),var(--hp-surface))}.communityPhotoStory h2{font-size:clamp(24px,4vw,38px);letter-spacing:-.045em;line-height:1.15;margin:0 0 12px}.communityPhotoStory .workspacePhoto{margin:0}.communityPhotoStory .workspacePhoto img{height:240px}.communityPhotoStory p{color:var(--hp-text-secondary);line-height:1.7}.communityPhotoStory .workspaceActions{margin-top:16px}.hero .cover img{object-fit:cover}
.cover.peopleCover{padding:0;min-height:0;overflow:hidden;border:1px solid var(--hp-border);background:var(--hp-surface);box-shadow:var(--hp-shadow);transform:none}.cover.peopleCover:before,.cover.peopleCover:after{display:none}.peopleCover .workspacePhoto{margin:0;border-radius:0}.peopleCover .workspacePhoto img{height:420px;object-position:center}.peopleCoverBadge{position:absolute;left:18px;bottom:54px;max-width:calc(100% - 36px);padding:12px 16px;border-radius:14px;background:var(--hp-accent);color:var(--hp-accent-contrast);font:800 13px Manrope,Arial,sans-serif}.workspaceMetric:nth-child(2){border-top:3px solid #37b9c2}.workspaceMetric:nth-child(3){border-top:3px solid #eab355}.workspaceMetric:nth-child(4){border-top:3px solid #9b8deb}.workspaceProfileHero{background:linear-gradient(120deg,var(--hp-hover),var(--hp-surface) 65%)}
@media(max-width:700px){.peopleCover .workspacePhoto img{height:280px}.peopleCoverBadge{font-size:12px;left:12px;bottom:48px;padding:10px 12px}}
@media(max-width:700px){.communityPhotoStory{grid-template-columns:minmax(0,1fr);padding:16px;gap:14px}.communityPhotoStory .workspacePhoto img{height:180px}}
@media(prefers-reduced-motion:no-preference){.workspaceCard,.workspaceMetric,.workspaceRequest,.workspaceCommunityNav button,.btn{transition:background .16s,border-color .16s,box-shadow .16s,transform .16s}.workspaceRequest:hover{border-color:var(--hp-accent-text);box-shadow:var(--hp-shadow)}.workspaceCommunityNav button:hover{transform:translateY(-2px)}}
.workspaceEmpty,.workspaceMessages,.messages,.input,.workspaceAccountNav,
.workspaceTag,.badge,.map,.adminSearch{background:var(--hp-surface-secondary);border-color:var(--hp-border);color:var(--hp-text-secondary)}
.input{background:var(--hp-input);color:var(--hp-text-primary)}
.workspaceTag.open,.badge.ok,.workspaceMiniIcon,.workspaceAppNotice{background:var(--hp-hover);color:var(--hp-success);border-color:var(--hp-border)}
.workspaceTag.progress,.badge.warn{background:var(--hp-surface-secondary);color:var(--hp-warning)}
.mapTask,.mapPrivacy{background:var(--hp-surface-secondary);border-color:var(--hp-border);color:var(--hp-text-primary)}.mapToolbar .muted{min-width:0}.mapTaskCopy{overflow-wrap:anywhere}.mapRouteInfo{color:var(--hp-accent-text)}
.workspaceRoute{background:var(--hp-surface);border-color:var(--hp-border)}
.workspaceMessage,.msg{background:var(--hp-surface-secondary);border-color:var(--hp-border);color:var(--hp-text-primary);overflow-wrap:anywhere}
.workspaceMessage.mine,.msg.mine{background:var(--hp-hover);border-color:var(--hp-border)}
.workspaceHeaderActions .btn,.light{background:var(--hp-surface);color:var(--hp-text-primary);border-color:var(--hp-border)}
.workspaceHeaderActions .btn.grad,.grad,.dark{background:var(--hp-accent);color:var(--hp-accent-contrast);border-color:var(--hp-accent)}
.grad:hover,.dark:hover{background:#c6ff83;color:var(--hp-accent-contrast)}
#sitePrimaryNav .active,#sitePrimaryNav button:hover,#sitePrimaryNav a:hover,
.workspaceSectionTabs button.active,.workspaceProfileTabs button.active{background:var(--hp-hover);color:var(--hp-accent-text);border-color:var(--hp-accent-text)}
.modal{background:var(--hp-overlay)}.modal.adminModal>.box.adminShell{background:var(--hp-surface)}
.close,.workspaceCard h2,.workspaceCard h3,.workspaceCard b,.workspaceMetric b,.workspaceMiniItem b{color:var(--hp-text-primary)}
.workspaceMetric:first-child b,.workspaceKicker,.workspaceStatus,.workspaceTransactionAmount,.workspaceWalletAmount b,.workspaceProductPrice{color:var(--hp-accent-text)}
.workspaceMiniItem,.workspaceTransaction,.workspaceInfoRow,.workspaceLeader,.workspaceCandidate{border-color:var(--hp-border)}
.workspaceInfoRow b,.workspaceRequestMain,.workspaceCandidateCopy,.workspaceMiniItem>div{min-width:0;overflow-wrap:anywhere}
.workspaceEmpty{padding:18px 14px}.workspaceSectionTabs{flex-wrap:wrap;overflow:visible}
.workspaceAccountLayout{display:grid;grid-template-columns:170px minmax(0,1fr);gap:24px;align-items:start}
.workspaceAccountNav{display:grid;gap:8px;padding:14px;border:1px solid var(--hp-border);border-radius:16px;position:sticky;top:95px}
.workspaceAccountNav b{font-size:12px;padding:4px 8px}.workspaceAccountNav button{width:100%;text-align:left;border:1px solid transparent;background:transparent;color:var(--hp-text-secondary);border-radius:10px;padding:12px 9px;font-size:12px;cursor:pointer}
.workspaceAccountNav button.active{background:var(--hp-hover);color:var(--hp-accent-text);border-color:var(--hp-border)}
.workspaceAccountMain{min-width:0}.workspaceProfileHero{display:flex;align-items:center;gap:20px;margin-bottom:16px}.workspaceProfileHero>div{min-width:0;flex:1}.workspaceProfileHero h2{margin:0}.workspaceProfileAvatar{display:grid;place-items:center;flex:0 0 80px;width:80px;height:80px;border:2px solid var(--hp-accent-text);border-radius:50%;background:var(--hp-hover);color:var(--hp-accent-text);font-size:28px;font-style:normal;font-weight:800}
.workspaceProfileHero p{overflow-wrap:anywhere}.workspaceAchievements{display:grid;gap:9px;margin-top:16px}.workspaceAchievement{padding:12px;border:1px solid var(--hp-border);border-radius:12px}.workspaceAchievement b,.workspaceAchievement small{display:block}.workspaceAchievement small{margin-top:4px;color:var(--hp-text-secondary)}
.workspaceProfileHero>div:not(.workspaceActions){flex:1 1 160px}.workspaceProfileHero>.workspaceActions{flex:0 0 auto;margin-top:0}
.workspaceHelpSearch{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;margin:14px 0}.workspaceHelpSearch .input{min-width:0}.workspaceHelpGrid .workspaceSide{min-width:0}
@media(max-width:900px){.workspaceHeaderActions .btn[onclick="authForm(false)"]{font-size:11px!important;width:auto!important;flex:0 0 auto!important;min-width:56px!important}.workspaceHeaderActions .btn[onclick="authForm(true)"]{display:none!important}}
.hero p,.heroMeta,.stepCard p,.safetyCard p,.landingMetric span{color:var(--hp-text-secondary)}.hero h1,.section h2{color:var(--hp-text-primary)}.hero h1 span,.ey,.heroMeta b{color:var(--hp-accent-text)}
.cover{border-color:var(--hp-border)}.toast{background:var(--hp-accent);color:var(--hp-accent-contrast)}.danger,.eventFormError,.workspaceInlineError{color:var(--hp-danger)}
@media(max-width:980px){.workspaceAccountLayout{grid-template-columns:145px minmax(0,1fr);gap:16px}.workspaceProfileHero{flex-wrap:wrap}}
@media(max-width:700px){.workspaceAccountLayout{grid-template-columns:minmax(0,1fr);gap:14px}.workspaceAccountNav{position:static;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px;padding:9px}.workspaceAccountNav b{grid-column:1/-1}.workspaceAccountNav button{padding:10px 7px}.workspaceProfileAvatar{flex-basis:60px;width:60px;height:60px;font-size:23px}.workspaceProfileHero{gap:12px}.workspaceProfileHero>.workspaceActions{flex:1 0 100%;width:100%;margin-top:0}.workspaceProfileHero>.workspaceActions .btn{width:100%}.workspaceHelpSearch{grid-template-columns:minmax(0,1fr)}}
'''

GAME_THEME_CSS = r'''
.topin{gap:8px}.gamesPrimaryNav{display:flex;justify-content:center;gap:4px;flex:1;min-width:0}.gamesPrimaryNav a{padding:10px 11px;color:var(--hp-text-secondary);text-decoration:none;font-size:12px;font-weight:800;border:1px solid transparent;border-radius:10px}.gamesPrimaryNav a[aria-current],.gamesPrimaryNav a:hover{color:var(--hp-accent-text);background:var(--hp-hover);border-color:var(--hp-border)}
.gameHelpLink,.sign,.gameRequestLink{padding:10px 12px;border:1px solid var(--hp-border);border-radius:10px;background:var(--hp-surface);color:var(--hp-text-primary);font-size:12px;text-decoration:none;font-weight:800;white-space:nowrap}.gameRequestLink{background:var(--hp-accent);color:var(--hp-accent-contrast)}.wallet{text-decoration:none;color:var(--hp-text-secondary)}
.top{background:var(--hp-header);border-color:var(--hp-border)}
.sign:hover{background:var(--hp-hover);color:var(--hp-text-primary)}
.wallet,.stat,.game-card,.store-card,.achievement,.metric,.control,.game-stage,
.cross-side,.dispatch-side,.match-side,.goal,.scenario,.mission .scenario,.end-card,
.panel,.daily{background:var(--hp-surface);border-color:var(--hp-border);color:var(--hp-text-primary)}
.game-copy p,.daily small,.game-note,.scenario p,.feedback p,.goal span,.dispatch-info{color:var(--hp-text-secondary)}
.tag,.route-stat div,.challenge,.entry,.achievement,.choice,.mission .choice,
.dispatch-info,.volunteer,.goal,.reward-line{border-color:var(--hp-border)}
.choice,.mission .choice,.volunteer,.direction,.hint-btn{background:var(--hp-surface-secondary);color:var(--hp-text-primary)}
.choice:hover,.mission .choice:hover,.direction:hover,.feedback,.game-note{background:var(--hp-hover);border-color:var(--hp-border)}
.tag{color:var(--hp-text-secondary)}.level,.mission .level{color:var(--hp-accent-text);border-color:var(--hp-border)}
.lesson,.mission,.end{background:radial-gradient(circle at 85% 10%,var(--hp-glow),transparent 50%),var(--hp-surface-secondary)}
.play,.feedback button,.pause-layer button{background:var(--hp-accent);color:var(--hp-accent-contrast)}
.pause-layer{background:var(--hp-overlay)}.toast{background:var(--hp-accent);color:var(--hp-accent-contrast)}
.goal b{color:var(--hp-text-primary)}.game-head,.title-block{min-width:0}
.cross-grid,.city,.match-field{--green:#b8f36b}
.dispatch-board.city{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-content:start;gap:12px;padding:20px}.dispatch-board .dispatch-hub{position:static;transform:none;grid-column:1/-1;border-radius:14px;min-height:80px;width:auto;height:auto;padding:15px}.dispatch-hub span{display:block;font-size:11px;font-weight:500;margin-top:5px}.dispatch-board .job-pin{position:static;transform:none;width:auto;min-width:0;min-height:100px;border-radius:13px;text-align:left;padding:14px;background:var(--hp-surface);color:var(--hp-text-primary);border:1px solid var(--hp-border)}.dispatch-board .job-pin:hover:not(:disabled){border-color:var(--hp-accent-text);background:var(--hp-hover)}.dispatch-board .job-pin b,.dispatch-board .job-pin small,.dispatch-board .job-pin span{display:block;overflow-wrap:anywhere}.dispatch-board .job-pin small{margin:7px 0;font-size:11px;color:var(--hp-text-secondary)}.dispatch-board .job-pin span{font-size:10px;color:var(--hp-accent-text)}.dispatch-board .job-pin.done{opacity:.65}.volunteer.active{border-color:var(--hp-accent-text);background:var(--hp-hover)}
@media(max-width:450px){.dispatch-board.city{padding:14px;gap:8px}.dispatch-board .job-pin{padding:11px}.volunteer i{font-size:10px}}
.dispatch-board .job-pin{position:relative;font-size:12px;height:auto}.dispatch-board .job-pin:before{display:none}.dispatch-board.city:before{pointer-events:none}
.match-game{grid-template-columns:minmax(0,1fr) 230px}
@media(max-width:700px){.match-game{grid-template-columns:minmax(0,1fr)}}
@media(max-width:900px){.gameHelpLink{display:none}.topin .wallet{display:none}.sign-full{display:none}.sign-short{display:inline}.sign,.gameRequestLink{display:grid;place-items:center;width:36px;height:38px;min-width:36px;padding:5px}.gameRequestLink span{font-size:0}.gameRequestLink:before{content:'+';font-size:19px}}
@media(max-width:420px){.gamesPrimaryNav{gap:2px}.gamesPrimaryNav a{display:grid;place-items:center;flex:0 0 28px;width:28px;height:34px;padding:0;font-size:0}.gamesPrimaryNav a:first-child:before{content:'⌂';font-size:16px}.gamesPrimaryNav a:nth-child(2):before{content:'?';font-size:15px}.gamesPrimaryNav a:nth-child(3):before{content:'▦';font-size:15px}.topin .brand img{width:85px}.topin{gap:5px}}
'''
