# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/21_vision.learner.ipynb.

# %% ../../nbs/21_vision.learner.ipynb 1
from __future__ import annotations
from ..basics import *
from .core import *
from .data import *
from .augment import *
from . import models

try: import timm
except ModuleNotFoundError: pass

# %% auto 0
__all__ = ['model_meta', 'has_pool_type', 'cut_model', 'create_body', 'create_head', 'default_split', 'add_head',
           'create_vision_model', 'TimmBody', 'create_timm_model', 'vision_learner', 'create_unet_model',
           'unet_learner', 'create_cnn_model', 'cnn_learner', 'show_results', 'plot_top_losses']

# %% ../../nbs/21_vision.learner.ipynb 7
def _is_pool_type(l): return re.search(r'Pool[123]d$', l.__class__.__name__)

# %% ../../nbs/21_vision.learner.ipynb 10
def has_pool_type(m):
    "Return `True` if `m` is a pooling layer or has one in its children"
    if _is_pool_type(m): return True
    for l in m.children():
        if has_pool_type(l): return True
    return False

# %% ../../nbs/21_vision.learner.ipynb 12
def _get_first_layer(m):
    "Access first layer of a model"
    c,p,n = m,None,None  # child, parent, name
    for n in next(m.named_parameters())[0].split('.')[:-1]:
        p,c=c,getattr(c,n)
    return c,p,n

# %% ../../nbs/21_vision.learner.ipynb 13
def _load_pretrained_weights(new_layer, previous_layer):
    "Load pretrained weights based on number of input channels"
    n_in = getattr(new_layer, 'in_channels')
    if n_in==1:
        # we take the sum
        new_layer.weight.data = previous_layer.weight.data.sum(dim=1, keepdim=True)
    elif n_in==2:
        # we take first 2 channels + 50%
        new_layer.weight.data = previous_layer.weight.data[:,:2] * 1.5
    else:
        # keep 3 channels weights and set others to null
        new_layer.weight.data[:,:3] = previous_layer.weight.data
        new_layer.weight.data[:,3:].zero_()

# %% ../../nbs/21_vision.learner.ipynb 14
def _update_first_layer(model, n_in, pretrained):
    "Change first layer based on number of input channels"
    if n_in == 3: return
    first_layer, parent, name = _get_first_layer(model)
    assert isinstance(first_layer, nn.Conv2d), f'Change of input channels only supported with Conv2d, found {first_layer.__class__.__name__}'
    assert getattr(first_layer, 'in_channels') == 3, f'Unexpected number of input channels, found {getattr(first_layer, "in_channels")} while expecting 3'
    params = {attr:getattr(first_layer, attr) for attr in 'out_channels kernel_size stride padding dilation groups padding_mode'.split()}
    params['bias'] = getattr(first_layer, 'bias') is not None
    params['in_channels'] = n_in
    new_layer = nn.Conv2d(**params)
    if pretrained:
        _load_pretrained_weights(new_layer, first_layer)
    setattr(parent, name, new_layer)

# %% ../../nbs/21_vision.learner.ipynb 15
def cut_model(model, cut):
    "Cut an instantiated model"
    if   isinstance(cut, int): return nn.Sequential(*list(model.children())[:cut])
    elif callable(cut): return cut(model)
    raise NameError("cut must be either integer or a function")

# %% ../../nbs/21_vision.learner.ipynb 16
def create_body(model, n_in=3, pretrained=True, cut=None):
    "Cut off the body of a typically pretrained `arch` as determined by `cut`"
    _update_first_layer(model, n_in, pretrained)
    if cut is None:
        ll = list(enumerate(model.children()))
        cut = next(i for i,o in reversed(ll) if has_pool_type(o))
    return cut_model(model, cut)

# %% ../../nbs/21_vision.learner.ipynb 20
def create_head(nf, n_out, lin_ftrs=None, ps=0.5, pool=True, concat_pool=True, first_bn=True, bn_final=False,
                lin_first=False, y_range=None):
    "Model head that takes `nf` features, runs through `lin_ftrs`, and out `n_out` classes."
    if pool and concat_pool: nf *= 2
    lin_ftrs = [nf, 512, n_out] if lin_ftrs is None else [nf] + lin_ftrs + [n_out]
    bns = [first_bn] + [True]*len(lin_ftrs[1:])
    ps = L(ps)
    if len(ps) == 1: ps = [ps[0]/2] * (len(lin_ftrs)-2) + ps
    actns = [nn.ReLU(inplace=True)] * (len(lin_ftrs)-2) + [None]
    layers = []
    if pool:
        pool = AdaptiveConcatPool2d() if concat_pool else nn.AdaptiveAvgPool2d(1)
        layers += [pool, Flatten()]
    if lin_first: layers.append(nn.Dropout(ps.pop(0)))
    for ni,no,bn,p,actn in zip(lin_ftrs[:-1], lin_ftrs[1:], bns, ps, actns):
        layers += LinBnDrop(ni, no, bn=bn, p=p, act=actn, lin_first=lin_first)
    if lin_first: layers.append(nn.Linear(lin_ftrs[-2], n_out))
    if bn_final: layers.append(nn.BatchNorm1d(lin_ftrs[-1], momentum=0.01))
    if y_range is not None: layers.append(SigmoidRange(*y_range))
    return nn.Sequential(*layers)

# %% ../../nbs/21_vision.learner.ipynb 24
from ..callback.hook import num_features_model

# %% ../../nbs/21_vision.learner.ipynb 26
def default_split(m):
    "Default split of a model between body and head"
    return L(m[0], m[1:]).map(params)

# %% ../../nbs/21_vision.learner.ipynb 28
def _xresnet_split(m): return L(m[0][:3], m[0][3:], m[1:]).map(params)
def  _resnet_split(m): return L(m[0][:6], m[0][6:], m[1:]).map(params)
def _squeezenet_split(m:nn.Module): return L(m[0][0][:5], m[0][0][5:], m[1:]).map(params)
def _densenet_split(m:nn.Module): return L(m[0][0][:7],m[0][0][7:], m[1:]).map(params)
def _vgg_split(m:nn.Module): return L(m[0][0][:22], m[0][0][22:], m[1:]).map(params)
def _alexnet_split(m:nn.Module): return L(m[0][0][:6], m[0][0][6:], m[1:]).map(params)

_default_meta    = {'cut':None, 'split':default_split}
_xresnet_meta    = {'cut':-4, 'split':_xresnet_split, 'stats':imagenet_stats}
_resnet_meta     = {'cut':-2, 'split':_resnet_split, 'stats':imagenet_stats}
_squeezenet_meta = {'cut':-1, 'split': _squeezenet_split, 'stats':imagenet_stats}
_densenet_meta   = {'cut':-1, 'split':_densenet_split, 'stats':imagenet_stats}
_vgg_meta        = {'cut':-2, 'split':_vgg_split, 'stats':imagenet_stats}
_alexnet_meta    = {'cut':-2, 'split':_alexnet_split, 'stats':imagenet_stats}

# %% ../../nbs/21_vision.learner.ipynb 29
model_meta = {
    models.xresnet.xresnet18 :{**_xresnet_meta}, models.xresnet.xresnet34: {**_xresnet_meta},
    models.xresnet.xresnet50 :{**_xresnet_meta}, models.xresnet.xresnet101:{**_xresnet_meta},
    models.xresnet.xresnet152:{**_xresnet_meta},

    models.resnet18 :{**_resnet_meta}, models.resnet34: {**_resnet_meta},
    models.resnet50 :{**_resnet_meta}, models.resnet101:{**_resnet_meta},
    models.resnet152:{**_resnet_meta},

    models.squeezenet1_0:{**_squeezenet_meta},
    models.squeezenet1_1:{**_squeezenet_meta},

    models.densenet121:{**_densenet_meta}, models.densenet169:{**_densenet_meta},
    models.densenet201:{**_densenet_meta}, models.densenet161:{**_densenet_meta},
    models.vgg11_bn:{**_vgg_meta}, models.vgg13_bn:{**_vgg_meta}, models.vgg16_bn:{**_vgg_meta}, models.vgg19_bn:{**_vgg_meta},
    models.alexnet:{**_alexnet_meta}}

# %% ../../nbs/21_vision.learner.ipynb 30
def add_head(body, nf, n_out, init=nn.init.kaiming_normal_, head=None, concat_pool=True, pool=True,
                lin_ftrs=None, ps=0.5, first_bn=True, bn_final=False, lin_first=False, y_range=None):
    "Add a head to a vision body"
    if head is None:
        head = create_head(nf, n_out, concat_pool=concat_pool, pool=pool,
                           lin_ftrs=lin_ftrs, ps=ps, first_bn=first_bn, bn_final=bn_final, lin_first=lin_first, y_range=y_range)
    model = nn.Sequential(body, head)
    if init is not None: apply_init(model[1], init)
    return model

# %% ../../nbs/21_vision.learner.ipynb 31
def create_vision_model(arch, n_out, pretrained=True, cut=None, n_in=3, init=nn.init.kaiming_normal_, custom_head=None,
                        concat_pool=True, pool=True, lin_ftrs=None, ps=0.5, first_bn=True, bn_final=False, lin_first=False, y_range=None):
    "Create custom vision architecture"
    meta = model_meta.get(arch, _default_meta)
    model = arch(pretrained=pretrained)
    body = create_body(model, n_in, pretrained, ifnone(cut, meta['cut']))
    nf = num_features_model(nn.Sequential(*body.children())) if custom_head is None else None
    return add_head(body, nf, n_out, init=init, head=custom_head, concat_pool=concat_pool, pool=pool,
                    lin_ftrs=lin_ftrs, ps=ps, first_bn=first_bn, bn_final=bn_final, lin_first=lin_first, y_range=y_range)

# %% ../../nbs/21_vision.learner.ipynb 35
class TimmBody(nn.Module):
    def __init__(self, model, pretrained:bool=True, cut=None, n_in:int=3):
        super().__init__()
        self.needs_pool = model.default_cfg.get('pool_size', None)
        self.model = model if cut is None else cut_model(model, cut)
    
    def forward(self,x): return self.model.forward_features(x) if self.needs_pool else self.model(x)

# %% ../../nbs/21_vision.learner.ipynb 36
def create_timm_model(arch, n_out, cut=None, pretrained=True, n_in=3, init=nn.init.kaiming_normal_, custom_head=None,
                     concat_pool=True, pool=True, lin_ftrs=None, ps=0.5, first_bn=True, bn_final=False, lin_first=False, y_range=None, **kwargs):
    "Create custom architecture using `arch`, `n_in` and `n_out` from the `timm` library"
    model = timm.create_model(arch, pretrained=pretrained, num_classes=0, in_chans=n_in, **kwargs)
    body = TimmBody(model, pretrained, None, n_in)
    nf = body.model.num_features
    res = add_head(body, nf, n_out, init=init, head=custom_head, concat_pool=concat_pool, pool=body.needs_pool,
                   lin_ftrs=lin_ftrs, ps=ps, first_bn=first_bn, bn_final=bn_final, lin_first=lin_first, y_range=y_range)
    return res,model.default_cfg

# %% ../../nbs/21_vision.learner.ipynb 38
def _add_norm(dls, meta, pretrained, n_in=3):
    if not pretrained: return
    stats = meta.get('stats')
    if stats is None: return
    if n_in != len(stats[0]): return
    if not dls.after_batch.fs.filter(risinstance(Normalize)):
        dls.add_tfms([Normalize.from_stats(*stats)],'after_batch')

# %% ../../nbs/21_vision.learner.ipynb 40
def _timm_norm(dls, cfg, pretrained, n_in=3):
    if not pretrained: return
    if n_in != len(cfg['mean']): return
    if not dls.after_batch.fs.filter(risinstance(Normalize)):
        tfm = Normalize.from_stats(cfg['mean'],cfg['std'])
        dls.add_tfms([tfm],'after_batch')

# %% ../../nbs/21_vision.learner.ipynb 41
@delegates(create_vision_model)
def vision_learner(dls, arch, normalize=True, n_out=None, pretrained=True, 
        # learner args
        loss_func=None, opt_func=Adam, lr=defaults.lr, splitter=None, cbs=None, metrics=None, path=None,
        model_dir='models', wd=None, wd_bn_bias=False, train_bn=True, moms=(0.95,0.85,0.95),
        # model & head args
        cut=None, init=nn.init.kaiming_normal_, custom_head=None, concat_pool=True, pool=True,
        lin_ftrs=None, ps=0.5, first_bn=True, bn_final=False, lin_first=False, y_range=None, **kwargs):
    "Build a vision learner from `dls` and `arch`"
    if n_out is None: n_out = get_c(dls)
    assert n_out, "`n_out` is not defined, and could not be inferred from data, set `dls.c` or pass `n_out`"
    meta = model_meta.get(arch, _default_meta)
    model_args = dict(init=init, custom_head=custom_head, concat_pool=concat_pool, pool=pool, lin_ftrs=lin_ftrs, ps=ps,
                      first_bn=first_bn, bn_final=bn_final, lin_first=lin_first, y_range=y_range, **kwargs)
    n_in = kwargs['n_in'] if 'n_in' in kwargs else 3
    if isinstance(arch, str):
        model,cfg = create_timm_model(arch, n_out, default_split, pretrained, **model_args)
        if normalize: _timm_norm(dls, cfg, pretrained, n_in)
    else:
        if normalize: _add_norm(dls, meta, pretrained, n_in)
        model = create_vision_model(arch, n_out, pretrained=pretrained, **model_args)
    
    splitter = ifnone(splitter, meta['split'])
    learn = Learner(dls=dls, model=model, loss_func=loss_func, opt_func=opt_func, lr=lr, splitter=splitter, cbs=cbs,
                   metrics=metrics, path=path, model_dir=model_dir, wd=wd, wd_bn_bias=wd_bn_bias, train_bn=train_bn, moms=moms)
    if pretrained: learn.freeze()
    # keep track of args for loggers
    store_attr('arch,normalize,n_out,pretrained', self=learn, **kwargs)
    return learn

# %% ../../nbs/21_vision.learner.ipynb 49
@delegates(models.unet.DynamicUnet.__init__)
def create_unet_model(arch, n_out, img_size, pretrained=True, cut=None, n_in=3, **kwargs):
    "Create custom unet architecture"
    meta = model_meta.get(arch, _default_meta)
    model = arch(pretrained=pretrained)
    body = create_body(model, n_in, pretrained, ifnone(cut, meta['cut']))    
    model = models.unet.DynamicUnet(body, n_out, img_size, **kwargs)
    return model

# %% ../../nbs/21_vision.learner.ipynb 52
@delegates(create_unet_model)
def unet_learner(dls, arch, normalize=True, n_out=None, pretrained=True, config=None,
                 # learner args
                 loss_func=None, opt_func=Adam, lr=defaults.lr, splitter=None, cbs=None, metrics=None, path=None,
                 model_dir='models', wd=None, wd_bn_bias=False, train_bn=True, moms=(0.95,0.85,0.95), **kwargs):    
    "Build a unet learner from `dls` and `arch`"
    
    if config:
        warnings.warn('config param is deprecated. Pass your args directly to unet_learner.')
        kwargs = {**config, **kwargs}
    
    meta = model_meta.get(arch, _default_meta)
    n_in = kwargs['n_in'] if 'n_in' in kwargs else 3
    if normalize: _add_norm(dls, meta, pretrained, n_in)
    
    n_out = ifnone(n_out, get_c(dls))
    assert n_out, "`n_out` is not defined, and could not be inferred from data, set `dls.c` or pass `n_out`"
    img_size = dls.one_batch()[0].shape[-2:]
    assert img_size, "image size could not be inferred from data"
    model = create_unet_model(arch, n_out, img_size, pretrained=pretrained, **kwargs)

    splitter = ifnone(splitter, meta['split'])
    learn = Learner(dls=dls, model=model, loss_func=loss_func, opt_func=opt_func, lr=lr, splitter=splitter, cbs=cbs,
                   metrics=metrics, path=path, model_dir=model_dir, wd=wd, wd_bn_bias=wd_bn_bias, train_bn=train_bn,
                   moms=moms)
    if pretrained: learn.freeze()
    # keep track of args for loggers
    store_attr('arch,normalize,n_out,pretrained', self=learn, **kwargs)
    return learn

# %% ../../nbs/21_vision.learner.ipynb 57
def create_cnn_model(*args, **kwargs):
    "Deprecated name for `create_vision_model` -- do not use"
    warn("`create_cnn_model` has been renamed to `create_vision_model` -- please update your code")
    return create_vision_model(*args, **kwargs)

# %% ../../nbs/21_vision.learner.ipynb 58
def cnn_learner(*args, **kwargs):
    "Deprecated name for `vision_learner` -- do not use"
    warn("`cnn_learner` has been renamed to `vision_learner` -- please update your code")
    return vision_learner(*args, **kwargs)

# %% ../../nbs/21_vision.learner.ipynb 60
@typedispatch
def show_results(x:TensorImage, y, samples, outs, ctxs=None, max_n=10, nrows=None, ncols=None, figsize=None, **kwargs):
    if ctxs is None: ctxs = get_grid(min(len(samples), max_n), nrows=nrows, ncols=ncols, figsize=figsize)
    ctxs = show_results[object](x, y, samples, outs, ctxs=ctxs, max_n=max_n, **kwargs)
    return ctxs

# %% ../../nbs/21_vision.learner.ipynb 61
@typedispatch
def show_results(x:TensorImage, y:TensorCategory, samples, outs, ctxs=None, max_n=10, nrows=None, ncols=None, figsize=None, **kwargs):
    if ctxs is None: ctxs = get_grid(min(len(samples), max_n), nrows=nrows, ncols=ncols, figsize=figsize)
    for i in range(2):
        ctxs = [b.show(ctx=c, **kwargs) for b,c,_ in zip(samples.itemgot(i),ctxs,range(max_n))]
    ctxs = [r.show(ctx=c, color='green' if b==r else 'red', **kwargs)
            for b,r,c,_ in zip(samples.itemgot(1),outs.itemgot(0),ctxs,range(max_n))]
    return ctxs

# %% ../../nbs/21_vision.learner.ipynb 62
@typedispatch
def show_results(x:TensorImage, y:TensorMask|TensorPoint|TensorBBox, samples, outs, ctxs=None, max_n=6,
                 nrows=None, ncols=1, figsize=None, **kwargs):
    if ctxs is None: ctxs = get_grid(min(len(samples), max_n), nrows=nrows, ncols=ncols, figsize=figsize, double=True,
                                     title='Target/Prediction')
    for i in range(2):
        ctxs[::2] = [b.show(ctx=c, **kwargs) for b,c,_ in zip(samples.itemgot(i),ctxs[::2],range(2*max_n))]
    for o in [samples,outs]:
        ctxs[1::2] = [b.show(ctx=c, **kwargs) for b,c,_ in zip(o.itemgot(0),ctxs[1::2],range(2*max_n))]
    return ctxs

# %% ../../nbs/21_vision.learner.ipynb 63
@typedispatch
def show_results(x:TensorImage, y:TensorImage, samples, outs, ctxs=None, max_n=10, figsize=None, **kwargs):
    if ctxs is None: ctxs = get_grid(3*min(len(samples), max_n), ncols=3, figsize=figsize, title='Input/Target/Prediction')
    for i in range(2):
        ctxs[i::3] = [b.show(ctx=c, **kwargs) for b,c,_ in zip(samples.itemgot(i),ctxs[i::3],range(max_n))]
    ctxs[2::3] = [b.show(ctx=c, **kwargs) for b,c,_ in zip(outs.itemgot(0),ctxs[2::3],range(max_n))]
    return ctxs

# %% ../../nbs/21_vision.learner.ipynb 64
@typedispatch
def plot_top_losses(x: TensorImage, y:TensorCategory, samples, outs, raws, losses, nrows=None, ncols=None, figsize=None, **kwargs):
    axs = get_grid(len(samples), nrows=nrows, ncols=ncols, figsize=figsize, title='Prediction/Actual/Loss/Probability')
    for ax,s,o,r,l in zip(axs, samples, outs, raws, losses):
        s[0].show(ctx=ax, **kwargs)
        ax.set_title(f'{o[0]}/{s[1]} / {l.item():.2f} / {r.max().item():.2f}')

# %% ../../nbs/21_vision.learner.ipynb 65
@typedispatch
def plot_top_losses(x: TensorImage, y:TensorMultiCategory, samples, outs, raws, losses, nrows=None, ncols=None, figsize=None, **kwargs):
    axs = get_grid(len(samples), nrows=nrows, ncols=ncols, figsize=figsize)
    for i,(ax,s) in enumerate(zip(axs, samples)): s[0].show(ctx=ax, title=f'Image {i}', **kwargs)
    rows = get_empty_df(len(samples))
    outs = L(s[1:] + o + (TitledStr(r), TitledFloat(l.item())) for s,o,r,l in zip(samples, outs, raws, losses))
    for i,l in enumerate(["target", "predicted", "probabilities", "loss"]):
        rows = [b.show(ctx=r, label=l, **kwargs) for b,r in zip(outs.itemgot(i),rows)]
    display_df(pd.DataFrame(rows))

# %% ../../nbs/21_vision.learner.ipynb 66
@typedispatch
def plot_top_losses(x:TensorImage, y:TensorMask, samples, outs, raws, losses, nrows=None, ncols=None, figsize=None, **kwargs):
    axes = get_grid(len(samples)*3, nrows=len(samples), ncols=3, figsize=figsize, flatten=False, title="Input | Target | Prediction")
    if axes.ndim == 1: axes = (axes,)
    titles = ["input", "target", "pred"]
    for axs,s,o,l in zip(axes, samples, outs, losses):
        imgs = (s[0], s[1], o[0])
        for ax,im,title in zip(axs, imgs, titles):
            if title=="pred": title += f"; loss = {l.item():.4f}"
            im.show(ctx=ax, **kwargs)
            ax.set_title(title)
