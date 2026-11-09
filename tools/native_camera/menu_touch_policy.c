#include "menu_touch_policy.h"
static int cancel(struct mt_state *s,int result) {
    if(s){s->armed=0;s->row=0;}return result;
}
int mt_decode(const uint8_t *raw,unsigned size,struct mt_event *out) {
    if(!raw || !out || size<24)return MT_INVALID;
    out->mouse=raw[0];out->button=raw[1];
    out->type=(uint32_t)raw[8]|((uint32_t)raw[9]<<8)|((uint32_t)raw[10]<<16)|((uint32_t)raw[11]<<24);
    return 0;
}
static int pick(const struct mt_context *c,const struct mt_event *e,const struct mt_ops *ops) {
    int16_t x,y;unsigned found=0;
    if(ops->position(ops->user,e->mouse,&x,&y)!=1)return MT_BACKEND;
    for(unsigned row=1;row<=c->rows;row++) {
        int hit=ops->hit(ops->user,row,x,y);
        if(hit!=0 && hit!=1)return MT_BACKEND;
        if(hit){if(found)return MT_AMBIGUOUS;found=row;}
    }
    return (int)found;
}
int mt_process(struct mt_state *s,const struct mt_context *c,const struct mt_event *e,const struct mt_ops *ops) {
    if(!s || !c || !e || !ops)return cancel(s,MT_INVALID);
    if(!c->active || !c->menu || !c->page || !c->generation)return cancel(s,MT_CANCELLED);
    if(!c->expected_tid || c->current_tid!=c->expected_tid)return cancel(s,MT_WRONG_THREAD);
    if(!c->rows || c->rows>6 || c->current_row>c->rows || c->mouse>3 ||
       !ops->position || !ops->hit || !ops->select || !ops->refresh)return cancel(s,MT_INVALID);
    if(e->mouse!=c->mouse)return cancel(s,MT_CANCELLED);
    /* Original press builder6309e54 emits5, release builder6309d48 emits6.
       Public postMouse* message tags0/1/2 are a DIFFERENT record format. */
    if(e->type==5) {
        if(e->button>=5)return cancel(s,MT_CANCELLED);
        int row=pick(c,e,ops);
        if(row<=0)return cancel(s,row<0?row:MT_CANCELLED);
        s->menu=c->menu;s->page=c->page;s->generation=c->generation;
        s->mouse=e->mouse;s->button=e->button;s->row=(unsigned)row;s->armed=1;
        return MT_ARMED;
    }
    if(!s->armed)return MT_IDLE;
    if(s->menu!=c->menu || s->page!=c->page || s->generation!=c->generation || s->mouse!=e->mouse)
        return cancel(s,MT_CANCELLED);
    if(e->type!=2 && e->type!=6)return cancel(s,MT_CANCELLED);
    if(e->type==6 && e->button!=s->button)return cancel(s,MT_CANCELLED);
    int row=pick(c,e,ops);
    if(row<0)return cancel(s,row);
    if(!row || (unsigned)row!=s->row)return cancel(s,MT_CANCELLED);
    if(e->type==2)return MT_ARMED;
    cancel(s,MT_IDLE); /* Disarm before callbacks/reentrancy. */
    if((unsigned)row==c->current_row)return MT_SAME;
    if(ops->select(ops->user,(unsigned)row)!=1)return MT_BACKEND;
    ops->refresh(ops->user);
    return MT_SELECTED;
}
