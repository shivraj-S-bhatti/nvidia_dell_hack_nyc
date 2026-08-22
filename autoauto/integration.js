(() => {
  'use strict';
  const data = RUN.integration;
  const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (character) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
  const shortHash = (value) => String(value || '').slice(0, 10).toUpperCase();
  const number = (value, digits = 2) => Number(value).toLocaleString(undefined, {maximumFractionDigits: digits});
  const proposalById = new Map(data.lab.proposals.map((candidate) => [candidate.id, candidate]));
  let activeCandidate = data.lab.proposals[0];
  let replaying = false;

  document.title = 'autoauto · Issues 42–47';
  document.querySelector('.claim').textContent = 'Generation corrected by assembly truth.';
  document.querySelector('.topmeta .mono').textContent = 'RUN S7';
  document.querySelectorAll('.viewtab')[1].textContent = 'Factory';

  const objectStage = document.querySelector('.object-stage');
  const viewport = document.createElement('div');
  viewport.className = 'evidence-viewport';
  viewport.innerHTML = `
    <div class="vehicle-surface" aria-label="Interactive NeoRacer assembly"></div>
    <img class="evidence-image" alt="Saved local engineering evidence" hidden>
    <div class="viewer-help"><b>DRAG</b> rotate <b>SCROLL</b> zoom <b>RIGHT-DRAG</b> pan <b>CLICK</b> select part</div>
    <button class="viewer-reset" type="button" title="Reset 3D view">↺ Reset view</button>
    <div class="evidence-caption"></div>`;
  objectStage.insertBefore(viewport, objectStage.firstChild);
  const vehicleSurface = viewport.querySelector('.vehicle-surface');
  const evidenceImage = viewport.querySelector('.evidence-image');
  const evidenceCaption = viewport.querySelector('.evidence-caption');
  const viewerHelp = viewport.querySelector('.viewer-help');
  const viewerReset = viewport.querySelector('.viewer-reset');
  const modes = document.querySelectorAll('.viewer-mode');
  let vehicleViewer = null;
  let vehicleFailed = false;

  function isFullVehicleAsset(asset) {
    return asset?.sha256 === data.object.fullVehicleImage.sha256;
  }

  function showInteractiveVehicle(title, detail) {
    evidenceCaption.innerHTML = `<b>${escapeHtml(title)}</b><br>${escapeHtml(detail)}<br>CLICKABLE · ${number(data.object.interactiveVehicle.counts.renderableLeafOccurrences, 0)} leaf occurrences`;
    evidenceImage.src = data.object.fullVehicleImage.url;
    evidenceImage.alt = title;
    evidenceImage.hidden = false;
    if (vehicleFailed) {
      vehicleSurface.hidden = true;
      viewerHelp.hidden = true;
      viewerReset.hidden = true;
      evidenceImage.classList.remove('vehicle-fallback');
      return;
    }
    evidenceImage.classList.add('vehicle-fallback');
    vehicleSurface.hidden = false;
    viewerHelp.hidden = false;
    viewerReset.hidden = false;
    vehicleViewer?.setVisible(true);
  }

  function setViewport(asset, title, detail) {
    if (isFullVehicleAsset(asset)) {
      showInteractiveVehicle(title, detail);
      return;
    }
    vehicleViewer?.setVisible(false);
    vehicleSurface.hidden = true;
    viewerHelp.hidden = true;
    viewerReset.hidden = true;
    evidenceImage.hidden = false;
    evidenceImage.classList.remove('vehicle-fallback');
    evidenceImage.classList.add('switching');
    window.setTimeout(() => {
      evidenceImage.src = asset.url;
      evidenceImage.alt = title;
      evidenceCaption.innerHTML = `<b>${escapeHtml(title)}</b><br>${escapeHtml(detail)}<br>SHA ${escapeHtml(shortHash(asset.sha256))}`;
      evidenceImage.classList.remove('switching');
    }, 90);
  }

  const stageTitle = document.querySelector('.stage-title');
  function setStageTitle(eyebrow, heading, subtitle, detail = '') {
    stageTitle.innerHTML = `<div class="eyebrow">${escapeHtml(eyebrow)}</div><h1>${escapeHtml(heading)}</h1><p>${escapeHtml(subtitle)}</p>${detail ? `<span class="artifact-hash">${escapeHtml(detail)}</span>` : ''}`;
  }
  vehicleViewer = window.AutoAutoVehicleViewer?.create({
    container: vehicleSurface,
    asset: data.object.interactiveVehicle,
    onDisplayReady: ({triangles}) => {
      if (!vehicleSurface.hidden) {
        evidenceImage.hidden = true;
        evidenceImage.classList.remove('vehicle-fallback');
        evidenceCaption.innerHTML = `<b>Complete NeoRacer assembly</b><br>${number(triangles, 0)} triangles visible<br>PREPARING CLICKABLE OCCURRENCES`;
      }
    },
    onReady: ({parts, triangles}) => {
      if (!vehicleSurface.hidden) {
        evidenceImage.hidden = true;
        evidenceImage.classList.remove('vehicle-fallback');
        evidenceCaption.innerHTML = `<b>Complete NeoRacer assembly</b><br>${number(parts, 0)} selectable leaf occurrences · ${number(triangles, 0)} triangles<br>CLICK A PART TO SELECT ITS SAVED ID`;
      }
    },
    onSelect: (part) => {
      if (!part) {
        setStageTitle('Complete physical object', data.object.assembly, `${number(data.object.occurrences, 0)} occurrences · ${number(data.object.definitions, 0)} component definitions`, 'Selection cleared');
        document.querySelectorAll('.bom-part').forEach((button) => button.classList.remove('active'));
        return;
      }
      const item = data.object.bom.find((candidate) => candidate.componentId === part.componentId);
      setStageTitle('Physical occurrence selected', item?.name || part.name, part.occurrencePath, part.occurrenceId);
      evidenceCaption.innerHTML = `<b>${escapeHtml(item?.name || part.name)}</b><br>${escapeHtml(part.occurrencePath)}<br>${escapeHtml(part.occurrenceId)}`;
      document.querySelectorAll('.bom-part').forEach((button) => button.classList.toggle('active', button.dataset.componentId === part.componentId));
    },
    onError: (error) => {
      console.error('Interactive vehicle unavailable', error);
      vehicleFailed = true;
      if (!vehicleSurface.hidden) showInteractiveVehicle('Complete NeoRacer assembly', 'Verified static fallback · interactive mesh unavailable');
    },
  }) || null;
  if (!vehicleViewer) vehicleFailed = true;
  window.setTimeout(() => {
    if (!vehicleViewer || vehicleViewer.displayReady) return;
    vehicleFailed = true;
    vehicleViewer.setVisible(false);
    showInteractiveVehicle('Complete NeoRacer assembly', 'Verified full-car fallback · interactive render timed out');
  }, 15000);
  viewerReset.onclick = () => {
    vehicleViewer?.reset();
    modes.forEach((button) => button.classList.toggle('active', button.dataset.viewerMode === 'assembled'));
    setStageTitle('Complete physical object', data.object.assembly, `${number(data.object.occurrences, 0)} occurrences · ${number(data.object.definitions, 0)} component definitions`, 'Interactive assembly reset');
  };
  setStageTitle('Complete physical object', data.object.assembly, `${number(data.object.occurrences, 0)} occurrences · ${number(data.object.definitions, 0)} component definitions`, 'Every saved part visible before target selection');
  document.querySelector('.command-label').textContent = 'EVIDENCE REPLAY';
  document.querySelector('#prompt').value = data.problem.objective + '. Preserve all four mount interfaces.';
  document.querySelector('#runButton').textContent = 'Replay Issues 42–47';
  document.querySelector('#candidateTray').hidden = true;
  document.querySelector('#completionCard').hidden = true;
  setViewport(data.object.fullVehicleImage, 'Complete NeoRacer assembly', `All ${data.object.occurrences} occurrences · ${number(data.object.fullVehicleImage.triangleCount, 0)} rendered triangles`);

  const bomButton = document.querySelector('#bomButton');
  const bomDrawer = document.querySelector('#bomDrawer');
  const bomGroups = document.querySelector('#bomGroups');
  document.querySelector('.bom-head h2').textContent = `NeoRacer · ${data.object.occurrences} occurrences`;
  function renderIntegratedBom(query = '') {
    const needle = query.trim().toLowerCase();
    const matches = data.object.bom.filter((item) => item.name.toLowerCase().includes(needle));
    const groups = [
      ['Root assembly', matches.filter((item) => item.isRootAssembly)],
      ['Repeated definitions', matches.filter((item) => !item.isRootAssembly && item.occurrenceCount > 1)],
      ['Single occurrences', matches.filter((item) => !item.isRootAssembly && item.occurrenceCount <= 1)],
    ].filter(([, items]) => items.length);
    bomGroups.innerHTML = groups.map(([label, items], index) => `<details class="bom-group" ${index === 0 || needle ? 'open' : ''}><summary>${escapeHtml(label)}<span class="bom-count">${items.length}</span></summary><div class="bom-parts">${items.map((item) => `<button class="bom-part" type="button" data-component-id="${escapeHtml(item.componentId)}"><b>${escapeHtml(item.name)}</b><span>${item.occurrenceCount}×</span></button>`).join('')}</div></details>`).join('');
  }
  renderIntegratedBom();
  bomButton.onclick = () => { bomDrawer.hidden = !bomDrawer.hidden; bomButton.setAttribute('aria-expanded', String(!bomDrawer.hidden)); };
  document.querySelector('#closeBom').onclick = () => { bomDrawer.hidden = true; bomButton.setAttribute('aria-expanded', 'false'); };
  document.querySelector('#bomSearch').oninput = (event) => renderIntegratedBom(event.target.value);
  bomGroups.onclick = (event) => {
    const button = event.target.closest('.bom-part');
    if (!button) return;
    const item = data.object.bom.find((candidate) => candidate.componentId === button.dataset.componentId);
    document.querySelectorAll('.bom-part').forEach((part) => part.classList.toggle('active', part === button));
    setViewport(data.object.fullVehicleImage, 'Complete NeoRacer assembly', `${item.name} selected from the Issue #42 component manifest`);
    modes.forEach((mode, index) => mode.classList.toggle('active', index === 0));
    vehicleViewer?.selectComponent(item.componentId);
    setStageTitle('Assembly component', item.name, `${item.occurrenceCount} physical occurrence${item.occurrenceCount === 1 ? '' : 's'} in the complete car`, item.componentId);
  };
  modes.forEach((button) => {
    button.onclick = () => {
      const mode = button.dataset.viewerMode;
      modes.forEach((item) => item.classList.toggle('active', item === button));
      setViewport(data.object.fullVehicleImage, 'Complete NeoRacer assembly', `${mode[0].toUpperCase()}${mode.slice(1)} interactive view`);
      if (mode === 'focus') vehicleViewer?.selectComponent(data.object.componentId);
      vehicleViewer?.setMode(mode);
      setStageTitle(
        mode === 'exploded' ? 'Exploded physical assembly' : mode === 'focus' ? 'Focused component inspection' : 'Complete physical object',
        mode === 'focus' ? data.object.targetName : data.object.assembly,
        mode === 'exploded' ? 'Parts separated from their saved assembly positions for inspection' : mode === 'focus' ? data.object.occurrencePath : `${number(data.object.occurrences, 0)} occurrences · ${number(data.object.definitions, 0)} component definitions`,
        mode === 'exploded' ? 'Inspection view only · source transforms remain unchanged' : mode === 'focus' ? data.object.componentId : 'Every saved part visible',
      );
    };
  });

  const review = document.querySelector('#reviewScreen .review');
  review.innerHTML = `
    <div class="review-head"><div><div class="eyebrow">Factory review · real saved run</div><h1>Three proposals compiled. One was vetoed.</h1><p>Every candidate received the same 13 deterministic checks. Track has not run.</p><span class="scope-note">Component-level comparison fixture · no vehicle certification claim</span></div><div class="review-actions"><button class="secondary" id="backButton">Review on object</button></div></div>
    <div class="summarybar"><div class="metric good"><span>Compiled CAD</span><b>${data.compile.countIncludingBaseline}</b></div><div class="metric good"><span>Proposal survivors</span><b>${data.factory.proposalSurvivors}</b></div><div class="metric"><span>Real veto</span><b>${data.factory.rejectedCandidateIds.length}</b></div><div class="metric"><span>Repeat verdict</span><b>${data.factory.repeatability.repetitions}/${data.factory.repeatability.repetitions}</b></div></div>
    <div class="review-grid"><div><div class="panel"><div class="panel-head"><strong>Compiled candidate family</strong><span>CLICK TO INSPECT · NO TRACK RANK</span></div><div class="variants" id="integratedVariants">${data.lab.proposals.map((candidate) => `
      <button type="button" class="variant ${candidate.factory.verdict === 'fail' ? 'failed' : 'survivor'}" data-candidate="${escapeHtml(candidate.id)}"><img src="${escapeHtml(candidate.compile.image.url)}" alt="Compiled ${escapeHtml(candidate.label)}"><div class="variant-copy"><strong>${escapeHtml(candidate.label)} <span class="${candidate.factory.verdict}">${candidate.factory.verdict === 'pass' ? 'SURVIVOR' : 'VETO'}</span></strong><dl><dt>Compiled material</dt><dd>${number(candidate.compile.materialFraction * 100, 1)}%</dd><dt>Solid / valid</dt><dd>${candidate.compile.solidCount} / YES</dd><dt>Factory</dt><dd>${candidate.factory.checksPassed}/${candidate.factory.checkCount}</dd></dl></div></button>`).join('')}</div><div class="pending-strip">${data.pendingStages.map((stage) => `<span class="pending-pill">${escapeHtml(stage)} · pending</span>`).join('')}</div></div>
      <div class="panel change-panel"><div class="panel-head"><strong>Evidence ledger</strong><span id="ledgerTitle">SELECT A CANDIDATE</span></div><div class="change-list" id="changeLedger"></div></div></div>
      <div><div class="panel"><div class="panel-head"><strong>Factory verdicts</strong><span>DETERMINISTIC · 3/3</span></div><div class="verdicts" id="integratedVerdicts">${data.lab.proposals.map((candidate) => `<div class="verdict" data-verdict="${escapeHtml(candidate.id)}"><div class="verdict-top"><span class="badge ${candidate.factory.verdict === 'fail' ? 'fail' : ''}">${candidate.factory.verdict === 'fail' ? 'VETO' : 'PASS'}</span><strong>${escapeHtml(candidate.label)}</strong></div><p>${candidate.factory.verdict === 'pass' ? `${candidate.factory.checksPassed}/${candidate.factory.checkCount} checks passed; eligible for future Track input.` : `${candidate.factory.failedChecks[0].check_id.replace('check.', '')}: ${number(candidate.factory.failedChecks[0].measured.value, 3)} ${candidate.factory.failedChecks[0].measured.unit} exceeds ${number(candidate.factory.failedChecks[0].threshold.value, 3)} ${candidate.factory.failedChecks[0].threshold.unit}.`}</p></div>`).join('')}</div></div>
      <div class="panel trace"><div class="panel-head"><strong>Measured critique</strong><span>FACTORY FEEDBACK</span></div><div class="trace-body" id="critiqueBody"></div></div></div></div>`;

  function ledgerRow(scope, before, after, delta, proof, tone = 'pass') {
    return `<div class="change-row"><span class="change-scope">${escapeHtml(scope)}</span><span class="change-value">${escapeHtml(before)}</span><span class="change-arrow">→</span><span class="change-value">${escapeHtml(after)}</span><b class="change-delta ${tone}">${escapeHtml(delta)}</b><small class="change-proof">${escapeHtml(proof)}</small></div>`;
  }

  function selectCandidate(candidate) {
    activeCandidate = candidate;
    document.querySelectorAll('[data-candidate]').forEach((element) => element.classList.toggle('selected', element.dataset.candidate === candidate.id));
    document.querySelectorAll('[data-verdict]').forEach((element) => element.classList.toggle('selected', element.dataset.verdict === candidate.id));
    document.querySelector('#ledgerTitle').textContent = `${candidate.shortId} · SHA ${shortHash(candidate.compile.geometrySha256)}`;
    const factoryTone = candidate.factory.verdict === 'pass' ? 'pass' : 'fail';
    document.querySelector('#changeLedger').innerHTML = [
      ledgerRow('Lab', `Seed ${candidate.seed}`, `${number(candidate.labEvaluation.materialFraction * 100, 2)}% density`, 'PROPOSED', candidate.labEvaluation.note),
      ledgerRow('CAD compile', `${candidate.compile.trueCells} cells`, `${number(candidate.compile.volumeMm3, 1)} mm³`, 'VALID STEP', `${number(candidate.compile.seconds, 2)} s · one closed solid`),
      ledgerRow('Factory', `${candidate.factory.checkCount} checks`, `${candidate.factory.checksPassed} passed`, candidate.factory.verdict.toUpperCase(), candidate.factory.verdictId, factoryTone),
      ledgerRow('Track', candidate.trackEligible ? 'Eligible' : 'Blocked', 'Not run', 'PENDING', candidate.trackEligible ? 'Present in the saved Factory survivor manifest.' : 'Rejected IDs are absent from Track input.', candidate.trackEligible ? 'pass' : 'fail'),
    ].join('');
    const failed = candidate.factory.failedChecks[0];
    document.querySelector('#critiqueBody').innerHTML = failed ? `
      <p class="trace-line fail-line"><i></i><span><b>${escapeHtml(failed.check_id)}</b> produced the veto.</span></p>
      <p class="trace-line"><i></i><span>Measured <b>${number(failed.measured.value, 3)} ${escapeHtml(failed.measured.unit)}</b> against a ${escapeHtml(failed.operator)} threshold of <b>${number(failed.threshold.value, 3)} ${escapeHtml(failed.threshold.unit)}</b>.</span></p>
      <p class="trace-line"><i></i><span>Feedback event <b>${escapeHtml(data.factory.feedback.id)}</b> retains the implicated component and requests a bounded local-density correction.</span></p>` : `
      <p class="trace-line"><i></i><span><b>${candidate.factory.checksPassed}/${candidate.factory.checkCount}</b> Factory checks passed.</span></p>
      <p class="trace-line"><i></i><span>Compiled geometry is one valid closed solid with all protected interfaces retained.</span></p>
      <p class="trace-line"><i></i><span>This is a Factory survivor, <b>not a ranked winner</b>. Track remains pending.</span></p>`;
  }

  document.querySelectorAll('[data-candidate]').forEach((element) => element.addEventListener('click', () => selectCandidate(proposalById.get(element.dataset.candidate))));
  selectCandidate(activeCandidate);

  const pendingEvents = data.pendingStages.map((name, index) => ({agent: ['TR','RV','HU'][index], name, text: 'Outside the Issue #42–47 integration boundary.', pending: true}));
  const allEvents = [...data.events, ...pendingEvents];
  function renderIntegrationEvents(active = -1) {
    document.querySelector('#activity').innerHTML = allEvents.map((event, index) => {
      const completed = !event.pending && index < active;
      const live = !event.pending && index === active;
      const state = event.pending ? 'PENDING' : completed ? 'DONE' : live ? 'LIVE' : 'WAIT';
      return `<div class="event ${completed ? 'done' : ''} ${live ? 'live' : ''} ${event.pending ? 'pending' : ''}"><div class="agent-icon">${escapeHtml(event.agent)}</div><div><strong>${escapeHtml(event.name)}<span class="time ${event.pending ? 'pending-time' : ''}">${state}</span></strong><p>${escapeHtml(event.text)}</p></div></div>`;
    }).join('');
  }

  const pause = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  async function replayIntegration() {
    if (replaying) return;
    replaying = true;
    showScreen('object');
    const button = document.querySelector('#runButton');
    button.disabled = true;
    button.classList.remove('replay-complete');
    document.querySelector('#runStatus').textContent = 'REPLAYING';
    document.querySelector('#dockTitle').textContent = 'Replaying saved evidence';
    document.querySelector('#dockSubtitle').textContent = 'Issues #42–47 · offline artifacts';
    renderIntegrationEvents(0);
    for (let index = 0; index < data.events.length; index += 1) {
      const event = data.events[index];
      renderIntegrationEvents(index);
      setViewport(event.image, event.name, event.text);
      if (event.heading) setStageTitle('Complete physical object', event.heading, event.subtitle, 'All physical occurrences loaded before target selection');
      else if (event.agent === 'OB') setStageTitle(data.object.assembly, data.object.targetName, `${data.object.protectedInterfaceCount} protected interfaces`, data.object.componentId);
      if (index === 4 || index === 5) document.querySelector('#flash').classList.add('on');
      await pause(480);
    }
    renderIntegrationEvents(data.events.length);
    document.querySelector('#runStatus').textContent = 'FACTORY REVIEW';
    document.querySelector('#dockTitle').textContent = 'Factory evidence ready';
    document.querySelector('#dockSubtitle').textContent = '2 survivors · 1 measured veto';
    button.disabled = false;
    button.textContent = 'Replay again';
    button.classList.add('replay-complete');
    showScreen('review');
    replaying = false;
  }

  document.querySelector('#runButton').onclick = replayIntegration;
  document.querySelector('#backButton').onclick = () => {
    showScreen('object');
    setViewport(activeCandidate.compile.image, `Compiled ${activeCandidate.label}`, `${activeCandidate.factory.verdict.toUpperCase()} · ${activeCandidate.factory.checksPassed}/${activeCandidate.factory.checkCount} Factory checks passed`);
    document.querySelector('#dockTitle').textContent = activeCandidate.label;
    document.querySelector('#dockSubtitle').textContent = activeCandidate.trackEligible ? 'Factory survivor · Track pending' : 'Factory veto · Track blocked';
  };
  renderIntegrationEvents();
  document.querySelector('#runStatus').textContent = 'READY';
})();
