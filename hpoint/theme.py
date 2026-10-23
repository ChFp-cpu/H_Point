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
.leagueCategoryTop{color:var(--hp-text-primary)}.leagueSectionHead p{color:var(--hp-text-secondary)}
.leagueRating,.leagueCategoryCount{color:var(--hp-accent-text)}
.leaguePill,.duoChampionScore,.leaguePosition,.duoRankBadge{background:var(--hp-hover);color:var(--hp-accent-text)}
.leagueProgressTrack,.leagueCategoryTrack{background:var(--hp-border);border-color:var(--hp-border)}
/* Photography stays in its original aspect ratio; frames carry the colour. */
.workspacePhoto{margin:0;min-width:0;background:transparent}
.workspacePhoto img,.hero .cover .workspacePhoto img{display:block;width:100%;height:auto;object-fit:contain}
.workspacePhoto figcaption{padding:6px 3px;color:var(--hp-text-secondary);font-size:9px;line-height:1.5}
.workspacePhoto figcaption a{color:inherit;text-decoration:none}
.workspacePhoto figcaption a:hover{text-decoration:underline}
.homeHero{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:42px;align-items:center;padding:16px 0 30px}
.homeHeroCopy{min-width:0}.homeHero .homeTitle{font-size:clamp(32px,4.2vw,58px);line-height:1.08;letter-spacing:-.055em;margin:17px 0 20px;max-width:650px}
.homeTitle span{color:var(--hp-accent-text)}
.homeHeroCopy>p{max-width:450px;line-height:1.75;color:var(--hp-text-secondary);font-size:15px}
.homeHeroCopy .workspaceActions{margin-top:24px;gap:10px}
.homeHeroCopy .btn{padding:13px 19px}.homeHeroCopy .btn span{margin-left:12px}
.homePersonal{display:flex;flex-wrap:wrap;gap:24px;margin-top:28px;padding-top:20px;border-top:1px solid var(--hp-border)}
.homePersonal button{border:0;background:transparent;padding:0;text-align:left;color:var(--hp-text-primary);cursor:pointer}
.homePersonal b,.homePersonal span{display:block}.homePersonal b{font-size:19px;letter-spacing:-.04em}.homePersonal span{font-size:11px;color:var(--hp-text-secondary);margin-top:4px}
.homePersonal button:hover b{color:var(--hp-accent-text)}
.peopleComposition{display:grid;grid-template-columns:minmax(0,.7fr) minmax(0,1fr);gap:6px 18px;position:relative;min-width:0;padding:10px 12px;isolation:isolate;overflow:clip}
.peopleComposition:before{content:'';position:absolute;inset:3% 2% 8% 12%;z-index:-1;background:var(--hp-accent);border-radius:40% 25% 45% 30%;opacity:.26;transform:rotate(7deg)}
.peopleFrame{min-width:0}.peopleFrameMain{grid-column:1/-1;margin-right:9%}
.peopleFrameMain img{border:7px solid #70c9c6;border-radius:46px 22px 22px 22px;box-shadow:var(--hp-shadow)}
.peopleFrameSmall{grid-column:2;margin:0 0 0 4px;transform:rotate(-3deg)}
.peopleFrameSmall img{border:7px solid #c5b7ee;border-radius:18px 18px 36px 18px;box-shadow:var(--hp-shadow)}
.peopleCompositionNote{align-self:center;justify-self:center;max-width:100%;padding:4px 0 12px 6px;transform:rotate(-6deg);color:var(--hp-accent-text)}
.peopleCompositionNote>span{display:block;color:#db8d42;font-size:42px;line-height:1;margin-bottom:9px}
.peopleCompositionNote b{font-size:clamp(16px,2vw,23px);letter-spacing:-.04em;line-height:1.15}
.cover.peopleCover{padding:0!important;min-height:0!important;overflow:visible;border:0;background:transparent;box-shadow:none;transform:none}
.cover.peopleCover:before,.cover.peopleCover:after{display:none}
.nav.guestHeader .in{grid-template-columns:minmax(0,1fr) auto!important;grid-template-areas:"brand actions"!important}.nav.guestHeader .sp{display:none!important}.nav.guestHeader #nav{display:flex!important;grid-area:actions;justify-content:flex-end;justify-self:end}.nav.guestHeader .workspaceHeaderActions .btn{display:inline-flex!important;flex:0 0 auto!important;font-size:12px!important;width:auto!important;min-width:0!important;padding:10px 14px!important}.nav.guestHeader .workspaceHeaderActions .btn:before,.nav.guestHeader .workspaceHeaderActions .btn:after{content:none!important}
@media(max-width:420px){.nav.guestHeader .in{gap:8px!important}.nav.guestHeader .workspaceHeaderActions{gap:6px!important}.nav.guestHeader .workspaceHeaderActions .btn{font-size:11px!important;padding:9px 10px!important}}
.welcomeComposition{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:12px 18px;align-items:center;position:relative;isolation:isolate;min-width:0;padding:18px 12px;overflow:clip}
.welcomeComposition:before{content:'';position:absolute;inset:13% 3% 12% 5%;background:var(--hp-accent);opacity:.18;border-radius:28% 48% 30% 45%;transform:rotate(-8deg);z-index:-1}
.welcomePhotoMain{grid-column:1;grid-row:1;align-self:end;min-width:0}.welcomePhotoMain img{border:6px solid #efbf7b;border-radius:42px 18px 18px 18px;box-shadow:var(--hp-shadow)}
.welcomePhotoSide{grid-column:2;grid-row:1/3;min-width:0;transform:rotate(3deg);margin:10px 6px 0 0}.welcomePhotoSide img{border:6px solid #85c9db;border-radius:60px 60px 20px 20px;box-shadow:var(--hp-shadow)}
.welcomePhotoNote{grid-column:1;grid-row:2;align-self:start;max-width:100%;margin:0;padding:4px 4px 12px 10px;color:var(--hp-accent-text);font-size:clamp(14px,1.65vw,21px);font-weight:800;line-height:1.3;letter-spacing:-.035em}
.welcomePhotoNote>span{display:block;color:#dd9b45;font-size:38px;margin-bottom:8px;line-height:1}
@media(max-width:700px){.welcomeComposition{width:100%;max-width:460px;margin:auto;padding:10px 6px;gap:10px}.welcomePhotoMain img,.welcomePhotoSide img{border-width:4px}.welcomePhotoMain img{border-radius:28px 12px 12px 12px}.welcomePhotoSide img{border-radius:40px 40px 14px 14px}.welcomePhotoNote{font-size:15px;padding-left:4px}.welcomePhotoNote>span{font-size:30px}}
.homeLeague{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr) 125px;gap:28px;align-items:center;background:var(--hp-hover);border:1px solid var(--hp-border);border-radius:24px;padding:30px;margin:8px 0 24px}
.homeLeagueIntro h2{font-size:30px;letter-spacing:-.04em;line-height:1.1;margin:10px 0}.homeLeagueIntro p{font-size:13px;line-height:1.6;color:var(--hp-text-secondary);max-width:340px}
.homeLeagueIntro .btn{margin-top:5px}.homeLeagueNumbers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px 18px}
.homeLeagueNumbers>div:last-child{grid-column:1/-1;border-top:1px solid var(--hp-border);padding-top:16px}
.homeLeagueNumbers b{display:block;font-size:34px;line-height:1.1;letter-spacing:-.05em}.homeLeagueNumbers span{display:block;font-size:11px;color:var(--hp-text-secondary);margin-top:5px}
.homeLeagueRing{border-radius:50%;width:125px;height:125px;padding:9px;background:conic-gradient(var(--hp-accent-text) var(--done),var(--hp-border) 0)}
.homeLeagueRing>div{display:grid;place-content:center;text-align:center;background:var(--hp-hover);height:100%;border-radius:50%}
.homeLeagueRing b{font-size:28px;letter-spacing:-.04em}.homeLeagueRing span{font-size:10px;color:var(--hp-text-secondary);line-height:1.4}
.homeTasks{margin-bottom:30px}.homeTasks h2{font-size:25px;line-height:1.25}.homeTasks .workspaceFocus{background:linear-gradient(135deg,var(--hp-surface),var(--hp-hover))}
.homeRecentList{display:grid;gap:0}.homeRecent{width:100%;display:flex;align-items:center;gap:12px;padding:14px 0;border:0;border-bottom:1px solid var(--hp-border);background:transparent;color:var(--hp-text-primary);text-align:left;cursor:pointer}
.homeRecent:last-child{border-bottom:0}.homeRecent>span:nth-child(2){min-width:0;flex:1}.homeRecent b,.homeRecent small{display:block;overflow-wrap:anywhere}.homeRecent b{font-size:12px;line-height:1.6}.homeRecent small{font-size:10px;color:var(--hp-text-secondary);margin-top:3px}.homeRecent:hover b{color:var(--hp-accent-text)}.homeRecent .workspaceMiniIcon{flex-shrink:0}
.homeTogether{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:40px;align-items:center;padding:20px 0 8px}
.homeTogetherPhoto{padding:16px;background:var(--hp-surface-secondary);border-radius:60px 22px 22px 22px;border:1px solid var(--hp-border)}
.homeTogetherPhoto img{border-radius:42px 12px 12px 12px}.homeTogetherCopy h2{font-size:clamp(24px,3vw,35px);line-height:1.15;letter-spacing:-.045em;margin:12px 0 16px}
.homeTogetherCopy{min-width:0}.homeTogetherCopy p{line-height:1.65}
.communityPhotoStory{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:28px;align-items:center;margin-bottom:24px;padding:24px;border:1px solid var(--hp-border);border-radius:24px;background:var(--hp-hover)}
.communityPhotoStory h2{font-size:clamp(24px,4vw,38px);letter-spacing:-.045em;line-height:1.15;margin:12px 0}
.communityPhotoStory p{color:var(--hp-text-secondary);line-height:1.7}.communityPhotoStory img{border:7px solid #e5b76d;border-radius:36px 16px 16px 16px}
.workspaceMetric:nth-child(2){border-top:3px solid #37b9c2}.workspaceMetric:nth-child(3){border-top:3px solid #eab355}.workspaceMetric:nth-child(4){border-top:3px solid #9b8deb}
.workspaceProfileHero{background:linear-gradient(120deg,var(--hp-hover),var(--hp-surface) 65%)}
@media(prefers-reduced-motion:no-preference){.peopleFrame{transition:transform .25s}.peopleFrameSmall:hover{transform:rotate(0deg) translateY(-3px)}.homeRecent{transition:color .16s}}
@media(max-width:980px){.homeHero{gap:20px}.homeLeague{gap:20px;padding:24px;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr)}.homeLeagueRing{display:none}.homeTogether{gap:24px}}
@media(max-width:700px){.homeHero{grid-template-columns:minmax(0,1fr);gap:12px;padding-top:8px}.homeHero .homeTitle{font-size:clamp(32px,8.3vw,46px);margin:12px 0 14px}.homeHeroCopy>p{font-size:14px}.homeHeroCopy .workspaceActions{margin-top:18px}.homeHeroCopy .btn{padding:12px 14px}.homePersonal{gap:22px;margin-top:20px;padding-top:16px}.homePersonal b{font-size:17px}.peopleComposition{max-width:460px;width:100%;margin:0 auto;padding:8px 8px;gap:4px 12px}.peopleFrameMain{margin-right:12%}.peopleFrameSmall{margin-left:0}.peopleFrameMain img,.peopleFrameSmall img{border-width:5px}.peopleFrameMain img{border-radius:32px 16px 16px 16px}.peopleCompositionNote>span{font-size:32px}.peopleCompositionNote b{font-size:19px}.homeLeague{grid-template-columns:minmax(0,1fr);padding:22px;gap:20px}.homeLeagueIntro h2{font-size:28px}.homeLeagueNumbers{grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;border-top:1px solid var(--hp-border);padding-top:18px}.homeLeagueNumbers>div:last-child{grid-column:auto;border:0;padding:0}.homeLeagueNumbers b{font-size:28px}.homeLeagueNumbers span{font-size:10px}.homeTogether,.communityPhotoStory{grid-template-columns:minmax(0,1fr);gap:20px}.homeTogether{padding-top:0}.homeTogetherPhoto{padding:10px}.communityPhotoStory{padding:18px}.homeTasks h2{font-size:22px}}
@media(prefers-reduced-motion:no-preference){.workspaceCard,.workspaceMetric,.workspaceRequest,.workspaceCommunityNav button,.btn{transition:background .16s,border-color .16s,box-shadow .16s,transform .16s}.workspaceRequest:hover{border-color:var(--hp-accent-text);box-shadow:var(--hp-shadow)}.workspaceCommunityNav button:hover{transform:translateY(-2px)}}
.workspaceEmpty,.workspaceMessages,.messages,.input,.workspaceAccountNav,
.workspaceTag,.badge,.map,.adminSearch{background:var(--hp-surface-secondary);border-color:var(--hp-border);color:var(--hp-text-secondary)}
.input{background:var(--hp-input);color:var(--hp-text-primary)}
.box h2,.box h3{color:var(--hp-text-primary)}
.passwordRules,.passwordHint,.passwordToggle{color:var(--hp-text-secondary)}
.passwordRules li.ok{color:var(--hp-success)}.passwordRules li.bad{color:var(--hp-danger)}
.passwordHint.good{color:var(--hp-success)!important}.passwordHint.bad{color:var(--hp-danger)!important}
.adminMetric b,.adminKicker{color:var(--hp-accent-text)}
.adminSub,.adminMetric span,.adminUserCopy span,.adminActivityItem span,.adminEmpty,.adminTicket small,.adminChartLabels{color:var(--hp-text-secondary)}
.adminBar b,.adminTicket p{color:var(--hp-text-primary)}
.adminTicket,.adminWorkspace .input{background:var(--hp-input);color:var(--hp-text-primary);border-color:var(--hp-border)}
.adminTop,.adminChart,.adminUser,.adminActivityItem{border-color:var(--hp-border)}
.adminWorkspace .danger{color:var(--hp-danger);border-color:var(--hp-danger)}
.modal.adminModal>.box.adminShell>.close{color:var(--hp-text-primary)}
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
.finish-control{width:auto!important;min-width:0;padding:9px 12px;font-size:11px}.cross-cell[data-bonus]:before{content:attr(data-bonus);position:absolute;inset:10% 12%;display:grid;place-items:center;border-radius:9px;background:#e5ff9e;color:#28451c;font-size:24px;box-shadow:0 2px 8px #163a2866}.playBonus{padding:10px;border-radius:10px;background:var(--hp-hover);color:var(--hp-accent-text)}.round-end .end-card{background:var(--hp-surface);color:var(--hp-text-primary)}
@media(max-width:700px){.controls{flex-wrap:wrap}.finish-control{flex:1;max-width:100%}}
.match-game{grid-template-columns:minmax(0,1fr) 230px}
@media(max-width:700px){.match-game{grid-template-columns:minmax(0,1fr)}}
@media(max-width:900px){.gameHelpLink{display:none}.topin .wallet{display:none}.sign-full{display:none}.sign-short{display:inline}.sign,.gameRequestLink{display:grid;place-items:center;width:36px;height:38px;min-width:36px;padding:5px}.gameRequestLink span{font-size:0}.gameRequestLink:before{content:'+';font-size:19px}}
@media(max-width:420px){.gamesPrimaryNav{gap:2px}.gamesPrimaryNav a{display:grid;place-items:center;flex:0 0 28px;width:28px;height:34px;padding:0;font-size:0}.gamesPrimaryNav a:first-child:before{content:'⌂';font-size:16px}.gamesPrimaryNav a:nth-child(2):before{content:'?';font-size:15px}.gamesPrimaryNav a:nth-child(3):before{content:'▦';font-size:15px}.topin .brand img{width:85px}.topin{gap:5px}}
'''
