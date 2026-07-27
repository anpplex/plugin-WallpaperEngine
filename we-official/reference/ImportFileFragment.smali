.class public final Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;
.super Landroidx/fragment/app/Fragment;
.source "ImportFileFragment.kt"


# annotations
.annotation system Ldalvik/annotation/MemberClasses;
    value = {
        Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$ChooseWallpapers;
    }
.end annotation

.annotation runtime Lkotlin/Metadata;
    d1 = {
        "\u00008\n\u0002\u0018\u0002\n\u0002\u0018\u0002\n\u0002\u0008\u0003\n\u0002\u0010\u000b\n\u0000\n\u0002\u0018\u0002\n\u0002\u0010\u0002\n\u0002\u0008\u0004\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0000\n\u0002\u0018\u0002\n\u0002\u0008\u0003\u0018\u00002\u00020\u0001:\u0001\u0015B\u0007\u00a2\u0006\u0004\u0008\u0002\u0010\u0003J&\u0010\u000c\u001a\u0004\u0018\u00010\r2\u0006\u0010\u000e\u001a\u00020\u000f2\u0008\u0010\u0010\u001a\u0004\u0018\u00010\u00112\u0008\u0010\u0012\u001a\u0004\u0018\u00010\u0013H\u0016J\u0008\u0010\u0014\u001a\u00020\u0008H\u0016R\u000e\u0010\u0004\u001a\u00020\u0005X\u0082\u000e\u00a2\u0006\u0002\n\u0000R\u001f\u0010\u0006\u001a\u0010\u0012\u000c\u0012\n \t*\u0004\u0018\u00010\u00080\u00080\u0007\u00a2\u0006\u0008\n\u0000\u001a\u0004\u0008\n\u0010\u000b\u00a8\u0006\u0016"
    }
    d2 = {
        "Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;",
        "Landroidx/fragment/app/Fragment;",
        "<init>",
        "()V",
        "canNavigate",
        "",
        "chooser",
        "Landroidx/activity/result/ActivityResultLauncher;",
        "",
        "kotlin.jvm.PlatformType",
        "getChooser",
        "()Landroidx/activity/result/ActivityResultLauncher;",
        "onCreateView",
        "Landroid/view/View;",
        "inflater",
        "Landroid/view/LayoutInflater;",
        "container",
        "Landroid/view/ViewGroup;",
        "savedInstanceState",
        "Landroid/os/Bundle;",
        "onResume",
        "ChooseWallpapers",
        "app"
    }
    k = 0x1
    mv = {
        0x2,
        0x2,
        0x0
    }
    xi = 0x30
.end annotation


# instance fields
.field private canNavigate:Z

.field private final chooser:Landroidx/activity/result/ActivityResultLauncher;
    .annotation system Ldalvik/annotation/Signature;
        value = {
            "Landroidx/activity/result/ActivityResultLauncher<",
            "Lkotlin/Unit;",
            ">;"
        }
    .end annotation
.end field


# direct methods
.method public constructor <init>()V
    .locals 2

    .line 26
    invoke-direct {p0}, Landroidx/fragment/app/Fragment;-><init>()V

    const/4 v0, 0x1

    .line 28
    iput-boolean v0, p0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->canNavigate:Z

    .line 46
    new-instance v0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$ChooseWallpapers;

    invoke-direct {v0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$ChooseWallpapers;-><init>()V

    check-cast v0, Landroidx/activity/result/contract/ActivityResultContract;

    new-instance v1, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda0;

    invoke-direct {v1, p0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda0;-><init>(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;)V

    invoke-virtual {p0, v0, v1}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->registerForActivityResult(Landroidx/activity/result/contract/ActivityResultContract;Landroidx/activity/result/ActivityResultCallback;)Landroidx/activity/result/ActivityResultLauncher;

    move-result-object v0

    const-string v1, "registerForActivityResult(...)"

    invoke-static {v0, v1}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullExpressionValue(Ljava/lang/Object;Ljava/lang/String;)V

    iput-object v0, p0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->chooser:Landroidx/activity/result/ActivityResultLauncher;

    return-void
.end method

.method static final chooser$lambda$0(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Ljava/util/List;)V
    .locals 2

    .line 47
    check-cast p0, Landroidx/fragment/app/Fragment;

    const/4 v0, 0x1

    new-array v0, v0, [Lkotlin/Pair;

    const-string v1, "list"

    invoke-static {v1, p1}, Lkotlin/TuplesKt;->to(Ljava/lang/Object;Ljava/lang/Object;)Lkotlin/Pair;

    move-result-object p1

    const/4 v1, 0x0

    aput-object p1, v0, v1

    invoke-static {v0}, Landroidx/core/os/BundleKt;->bundleOf([Lkotlin/Pair;)Landroid/os/Bundle;

    move-result-object p1

    const-string v0, "wallpaperImport"

    invoke-static {p0, v0, p1}, Landroidx/fragment/app/FragmentKt;->setFragmentResult(Landroidx/fragment/app/Fragment;Ljava/lang/String;Landroid/os/Bundle;)V

    return-void
.end method

.method static final onCreateView$lambda$1(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Landroid/view/View;)V
    .locals 1

    # 车机适配：原「与计算机配对」→ 扫码导入（Motif WE）
    const-string p1, "qr"

    invoke-static {p0, p1}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->launchMotifWe(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Ljava/lang/String;)V

    return-void
.end method

.method static final onCreateView$lambda$5(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Landroid/view/View;)V
    .locals 1

    # 车机适配：文案仍为「导入文件」，实际扫描适配目录（Motif WE）
    const-string p1, "scan"

    invoke-static {p0, p1}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->launchMotifWe(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Ljava/lang/String;)V

    return-void
.end method

.method private static launchMotifWe(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Ljava/lang/String;)V
    .locals 4

    iget-boolean v0, p0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->canNavigate:Z

    if-eqz v0, :cond_end

    const/4 v0, 0x0

    iput-boolean v0, p0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->canNavigate:Z

    new-instance v0, Landroid/content/Intent;

    invoke-direct {v0}, Landroid/content/Intent;-><init>()V

    new-instance v1, Landroid/content/ComponentName;

    const-string v2, "com.motif.wallpaperengine"

    const-string v3, "com.motif.wallpaperengine.MainActivity"

    invoke-direct {v1, v2, v3}, Landroid/content/ComponentName;-><init>(Ljava/lang/String;Ljava/lang/String;)V

    invoke-virtual {v0, v1}, Landroid/content/Intent;->setComponent(Landroid/content/ComponentName;)Landroid/content/Intent;

    const-string v1, "we_mode"

    invoke-virtual {v0, v1, p1}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;

    const/high16 v1, 0x10000000

    invoke-virtual {v0, v1}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;

    :try_start_0
    invoke-virtual {p0, v0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->startActivity(Landroid/content/Intent;)V
    :try_end_0
    .catchall {:try_start_0 .. :try_end_0} :catchall_0

    goto :cond_end

    :catchall_0
    const/4 v0, 0x1

    iput-boolean v0, p0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->canNavigate:Z

    :cond_end
    return-void
.end method

.method private static final onCreateView$lambda$5$lambda$2(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Landroid/content/DialogInterface;I)V
    .locals 3

    .line 76
    sget-object p2, Lio/wallpaperengine/weutil/Util;->Companion:Lio/wallpaperengine/weutil/Util$Companion;

    invoke-virtual {p0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->requireContext()Landroid/content/Context;

    move-result-object v0

    const-string v1, "requireContext(...)"

    invoke-static {v0, v1}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullExpressionValue(Ljava/lang/Object;Ljava/lang/String;)V

    const-string v1, "hasShownExtendedStorageAlert"

    const/4 v2, 0x1

    invoke-virtual {p2, v0, v1, v2}, Lio/wallpaperengine/weutil/Util$Companion;->storeBoolean(Landroid/content/Context;Ljava/lang/String;Z)V

    .line 77
    invoke-interface {p1}, Landroid/content/DialogInterface;->dismiss()V

    .line 79
    :try_start_0
    iget-object p0, p0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->chooser:Landroidx/activity/result/ActivityResultLauncher;

    const/4 p1, 0x0

    invoke-static {p0, p1, v2, p1}, Landroidx/activity/result/ActivityResultLauncherKt;->launchUnit$default(Landroidx/activity/result/ActivityResultLauncher;Landroidx/core/app/ActivityOptionsCompat;ILjava/lang/Object;)V
    :try_end_0
    .catchall {:try_start_0 .. :try_end_0} :catchall_0

    :catchall_0
    return-void
.end method

.method private static final onCreateView$lambda$5$lambda$3(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Landroid/content/DialogInterface;I)V
    .locals 0

    const/4 p1, 0x1

    .line 84
    iput-boolean p1, p0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->canNavigate:Z

    return-void
.end method

.method private static final onCreateView$lambda$5$lambda$4(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Landroid/content/DialogInterface;)V
    .locals 0

    const/4 p1, 0x1

    .line 86
    iput-boolean p1, p0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->canNavigate:Z

    return-void
.end method

.method static final onCreateView$lambda$8(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Landroid/view/View;)V
    .locals 2

    .line 98
    invoke-virtual {p0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->requireContext()Landroid/content/Context;

    move-result-object p1

    sget v0, Lio/wallpaperengine/weclient/R$layout;->alert_workshop_info:I

    const/4 v1, 0x0

    invoke-static {p1, v0, v1}, Landroid/view/View;->inflate(Landroid/content/Context;ILandroid/view/ViewGroup;)Landroid/view/View;

    move-result-object p1

    .line 99
    sget v0, Lio/wallpaperengine/weclient/R$id;->btnInfo:I

    invoke-virtual {p1, v0}, Landroid/view/View;->findViewById(I)Landroid/view/View;

    move-result-object v0

    check-cast v0, Landroid/widget/Button;

    new-instance v1, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda1;

    invoke-direct {v1, p0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda1;-><init>(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;)V

    invoke-virtual {v0, v1}, Landroid/widget/Button;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    .line 103
    new-instance v0, Landroidx/appcompat/app/AlertDialog$Builder;

    invoke-virtual {p0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->requireContext()Landroid/content/Context;

    move-result-object v1

    invoke-direct {v0, v1}, Landroidx/appcompat/app/AlertDialog$Builder;-><init>(Landroid/content/Context;)V

    .line 104
    sget v1, Lio/wallpaperengine/weclient/R$string;->dialog_workshop_info_title:I

    invoke-virtual {p0, v1}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->getString(I)Ljava/lang/String;

    move-result-object v1

    check-cast v1, Ljava/lang/CharSequence;

    invoke-virtual {v0, v1}, Landroidx/appcompat/app/AlertDialog$Builder;->setTitle(Ljava/lang/CharSequence;)Landroidx/appcompat/app/AlertDialog$Builder;

    move-result-object v0

    .line 105
    invoke-virtual {v0, p1}, Landroidx/appcompat/app/AlertDialog$Builder;->setView(Landroid/view/View;)Landroidx/appcompat/app/AlertDialog$Builder;

    move-result-object p1

    .line 106
    sget v0, Lio/wallpaperengine/weclient/R$string;->dialog_prompt_btn_close:I

    invoke-virtual {p0, v0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->getString(I)Ljava/lang/String;

    move-result-object p0

    check-cast p0, Ljava/lang/CharSequence;

    new-instance v0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda2;

    invoke-direct {v0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda2;-><init>()V

    invoke-virtual {p1, p0, v0}, Landroidx/appcompat/app/AlertDialog$Builder;->setPositiveButton(Ljava/lang/CharSequence;Landroid/content/DialogInterface$OnClickListener;)Landroidx/appcompat/app/AlertDialog$Builder;

    move-result-object p0

    .line 109
    invoke-virtual {p0}, Landroidx/appcompat/app/AlertDialog$Builder;->create()Landroidx/appcompat/app/AlertDialog;

    move-result-object p0

    invoke-virtual {p0}, Landroidx/appcompat/app/AlertDialog;->show()V

    return-void
.end method

.method static final onCreateView$lambda$8$lambda$6(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;Landroid/view/View;)V
    .locals 1

    .line 100
    sget-object p1, Lio/wallpaperengine/weutil/Util;->Companion:Lio/wallpaperengine/weutil/Util$Companion;

    invoke-virtual {p0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->requireContext()Landroid/content/Context;

    move-result-object p0

    const-string v0, "requireContext(...)"

    invoke-static {p0, v0}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullExpressionValue(Ljava/lang/Object;Ljava/lang/String;)V

    const-string v0, "https://help.wallpaperengine.io/mobile/pairing.html"

    invoke-virtual {p1, p0, v0}, Lio/wallpaperengine/weutil/Util$Companion;->openURL(Landroid/content/Context;Ljava/lang/String;)V

    return-void
.end method

.method static final onCreateView$lambda$8$lambda$7(Landroid/content/DialogInterface;I)V
    .locals 0

    .line 107
    invoke-interface {p0}, Landroid/content/DialogInterface;->dismiss()V

    return-void
.end method


# virtual methods
.method public final getChooser()Landroidx/activity/result/ActivityResultLauncher;
    .locals 0
    .annotation system Ldalvik/annotation/Signature;
        value = {
            "()",
            "Landroidx/activity/result/ActivityResultLauncher<",
            "Lkotlin/Unit;",
            ">;"
        }
    .end annotation

    .line 46
    iget-object p0, p0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->chooser:Landroidx/activity/result/ActivityResultLauncher;

    return-object p0
.end method

.method public onCreateView(Landroid/view/LayoutInflater;Landroid/view/ViewGroup;Landroid/os/Bundle;)Landroid/view/View;
    .locals 2

    const-string p3, "inflater"

    invoke-static {p1, p3}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullParameter(Ljava/lang/Object;Ljava/lang/String;)V

    .line 55
    sget p3, Lio/wallpaperengine/weclient/R$layout;->fragment_import:I

    const/4 v0, 0x0

    invoke-virtual {p1, p3, p2, v0}, Landroid/view/LayoutInflater;->inflate(ILandroid/view/ViewGroup;Z)Landroid/view/View;

    move-result-object p1

    .line 56
    sget p2, Lio/wallpaperengine/weclient/R$id;->btDownloadFromPC:I

    invoke-virtual {p1, p2}, Landroid/view/View;->findViewById(I)Landroid/view/View;

    move-result-object p2

    const-string p3, "findViewById(...)"

    invoke-static {p2, p3}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullExpressionValue(Ljava/lang/Object;Ljava/lang/String;)V

    check-cast p2, Landroid/widget/Button;

    .line 57
    sget v0, Lio/wallpaperengine/weclient/R$id;->btImportLocally:I

    invoke-virtual {p1, v0}, Landroid/view/View;->findViewById(I)Landroid/view/View;

    move-result-object v0

    invoke-static {v0, p3}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullExpressionValue(Ljava/lang/Object;Ljava/lang/String;)V

    check-cast v0, Landroid/widget/Button;

    .line 58
    sget v1, Lio/wallpaperengine/weclient/R$id;->btImportWorkshophint:I

    invoke-virtual {p1, v1}, Landroid/view/View;->findViewById(I)Landroid/view/View;

    move-result-object v1

    invoke-static {v1, p3}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullExpressionValue(Ljava/lang/Object;Ljava/lang/String;)V

    check-cast v1, Landroid/widget/Button;

    .line 60
    new-instance p3, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda3;

    invoke-direct {p3, p0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda3;-><init>(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;)V

    invoke-virtual {p2, p3}, Landroid/widget/Button;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    .line 68
    new-instance p2, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda4;

    invoke-direct {p2, p0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda4;-><init>(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;)V

    invoke-virtual {v0, p2}, Landroid/widget/Button;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    .line 97
    new-instance p2, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda5;

    invoke-direct {p2, p0}, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment$$ExternalSyntheticLambda5;-><init>(Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;)V

    invoke-virtual {v1, p2}, Landroid/widget/Button;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    return-object p1
.end method

.method public onResume()V
    .locals 1

    .line 117
    invoke-super {p0}, Landroidx/fragment/app/Fragment;->onResume()V

    const/4 v0, 0x1

    .line 118
    iput-boolean v0, p0, Lio/wallpaperengine/weclient/ui/importfile/ImportFileFragment;->canNavigate:Z

    return-void
.end method
