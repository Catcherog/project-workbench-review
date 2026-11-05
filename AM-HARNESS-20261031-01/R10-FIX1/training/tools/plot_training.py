from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
T=Path(__file__).resolve().parents[1];v=json.loads((T/'evidence/training-metrics.json').read_text());steps=v['steps'];dev=v['dev']
plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold'})
fig,axes=plt.subplots(1,2,figsize=(12,4.7),gridspec_kw={'width_ratios':[1.55,1]})
ax=axes[0];x=[s['optimizer_step'] for s in steps];y=[s['loss'] for s in steps]
ax.plot(x,y,color='#245ec7',marker='o',linewidth=2);ax.set_xticks(x);ax.set_ylim(0,2.55);ax.set_title('Training loss by optimizer step',loc='left');ax.set_xlabel('Step (different four-example batches)');ax.set_ylabel('Cross-entropy (nats/token)');ax.grid(axis='y',alpha=.2)
for xx,yy in zip(x,y):ax.annotate(f'{yy:.5f}',(xx,yy),xytext=(0,11),textcoords='offset points',ha='center',fontsize=9)
ax=axes[1];values=[dev['before']['token_weighted_cross_entropy'],dev['after']['token_weighted_cross_entropy']]
bars=ax.bar(['Base','SFT'],values,color=['#8a96a8','#245ec7'],width=.52);ax.set_ylim(0,1.95);ax.set_title('Same 8-example development set',loc='left');ax.set_ylabel('Cross-entropy (nats/token)');ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
for b,z in zip(bars,values):ax.text(b.get_x()+b.get_width()/2,z+.045,f'{z:.6f}',ha='center')
delta=values[1]-values[0];ax.text(.5,.45,f'Change: {delta:+.6f}\n({delta/values[0]*100:+.2f}%)',ha='center',transform=ax.transAxes)
fig.suptitle('Synthetic SFT pilot · 32 training examples · 1 epoch · 8 updates',x=.05,ha='left',fontsize=14,fontweight='bold')
fig.text(.05,.025,'Training batches differ. Development loss improvement is not proof of business accuracy.',fontsize=10,color='#596272')
fig.tight_layout(rect=(.03,.07,1,.92));fig.savefig(T/'evidence/sft_loss.png',dpi=180,facecolor='white');fig.savefig(T/'evidence/sft_loss.svg',facecolor='white')
print(str(T/'evidence/sft_loss.png'))
